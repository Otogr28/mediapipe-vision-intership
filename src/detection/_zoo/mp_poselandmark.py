"""BlazePose landmark stage (onnxruntime).

Second stage of the GPU pose pipeline: given a person detection from
``MPPersonDet`` (box + 4 alignment keypoints), this builds the rotated
region-of-interest exactly like MediaPipe's ``pose_detection_to_roi`` +
``pose_landmark_by_roi`` graphs, crops it, runs the BlazePose landmark ONNX,
and decodes the raw tensors into

* 33 image landmarks — ``x``/``y`` normalized to [0, 1] in the ORIGINAL frame,
  ``z`` (hip-relative, roughly image-normalized), ``visibility`` (sigmoid).
* 33 world landmarks — metric ``x``/``y``/``z`` (meters, origin at the hips),
  gravity-aligned and camera-independent — MediaPipe's ``pose_world_landmarks``.

The landmark ONNX is tf2onnx-converted from the same ``pose_landmarks_detector``
that ships in ``models/pose_landmarker_lite.task`` (so it matches what the
MediaPipe path already produced). Its outputs are picked BY SHAPE, so the
runtime's Identity/Identity_N naming does not matter:
  * (1, 195) -> 39 x [x, y, z, visibility, presence] image landmarks
  * (1, 117) -> 39 x [x, y, z] world landmarks
  * (1, 1)   -> pose-presence score

The ROI geometry (``_detections_to_rect`` / ``_rect_transformation`` /
``_rotated_rect_to_points``) and the landmark decode are ported from
geaxgx/depthai_blazepose (MIT), which mirrors the MediaPipe reference graph.
onnxruntime is imported lazily so the default MediaPipe path never needs it.
"""

from math import atan2, cos, floor, pi, sin, sqrt

import cv2 as cv
import numpy as np

# 33 body landmarks are the app-facing pose; the model emits 39 (33 + 6 aux)
# in the image tensor and the same in the world tensor.
NUM_POSE_LANDMARKS = 33
LM_INPUT_SIZE = 256          # the landmark model's square input (px)
# scale_x/scale_y=1.25 + square_long, the "Version 084" RectTransformation the
# BlazePose full-body graph uses to expand the detection into the landmark ROI.
ROI_SCALE = 1.25


class _Body:
    """Mutable bag of ROI attributes (mirrors geaxgx's Body for the port)."""
    __slots__ = ("pd_kps", "rect_w", "rect_h", "rect_x_center", "rect_y_center",
                 "rotation", "rect_x_center_a", "rect_y_center_a",
                 "rect_w_a", "rect_h_a", "rect_points")


def _normalize_radians(angle):
    return angle - 2 * pi * floor((angle + pi) / (2 * pi))


def _detections_to_rect(body, kp_pair=(0, 1)):
    """Center/size/rotation of the ROI from two alignment keypoints.

    Works in PIXELS (isotropic) rather than the reference's square-normalized
    space: our detector returns keypoints in original-image pixels and the frame
    is not square, so normalizing x by width and y by height would stretch the
    box/rotation (a 640x360 frame otherwise inflates the ROI ~2x on the long
    axis). kp 0 = hip center, kp 1 = full-body point (per the detector). Target
    angle 90 deg — AlignmentPointsRectsCalculator."""
    target_angle = pi * 0.5
    x_center, y_center = body.pd_kps[kp_pair[0]]
    x_scale, y_scale = body.pd_kps[kp_pair[1]]
    box_size = sqrt((x_scale - x_center) ** 2 + (y_scale - y_center) ** 2) * 2
    body.rect_w = box_size
    body.rect_h = box_size
    body.rect_x_center = x_center
    body.rect_y_center = y_center
    rotation = target_angle - atan2(-(y_scale - y_center), x_scale - x_center)
    body.rotation = _normalize_radians(rotation)


def _rotated_rect_to_points(cx, cy, w, h, rotation):
    b = cos(rotation) * 0.5
    a = sin(rotation) * 0.5
    p0x = cx - a * h - b * w
    p0y = cy + b * h - a * w
    p1x = cx + a * h - b * w
    p1y = cy - b * h - a * w
    p2x = 2 * cx - p0x
    p2y = 2 * cy - p0y
    p3x = 2 * cx - p1x
    p3y = 2 * cy - p1y
    return [[p0x, p0y], [p1x, p1y], [p2x, p2y], [p3x, p3y]]


def _rect_transformation(body, scale=ROI_SCALE):
    """Expand the raw rect into the padded, square landmark ROI (all in pixels).

    shift_x/shift_y are 0 for the full-body pose graph, so the center is
    unchanged; square_long + scale 1.25 is the "Version 084" RectTransformation."""
    body.rect_x_center_a = body.rect_x_center
    body.rect_y_center_a = body.rect_y_center
    long_side = max(body.rect_w, body.rect_h)   # square_long: true
    body.rect_w_a = long_side * scale
    body.rect_h_a = long_side * scale
    body.rect_points = _rotated_rect_to_points(
        body.rect_x_center_a, body.rect_y_center_a,
        body.rect_w_a, body.rect_h_a, body.rotation)


def _warp_rect_img(rect_points, img, w, h):
    # rect_points[0] is the bottom-left point; [1:] are the 3 that define the
    # affine mapping into a w x h upright crop.
    src = np.array(rect_points[1:], dtype=np.float32)
    dst = np.array([(0, 0), (w, 0), (w, h)], dtype=np.float32)
    mat = cv.getAffineTransform(src, dst)
    return cv.warpAffine(img, mat, (w, h))


class _Landmark:
    """Attribute-compatible with MediaPipe's NormalizedLandmark (x/y/z/visibility)."""
    __slots__ = ("x", "y", "z", "visibility", "presence")

    def __init__(self, x, y, z=0.0, visibility=None, presence=None):
        self.x = x
        self.y = y
        self.z = z
        self.visibility = visibility
        self.presence = presence


class MPPoseLandmark:
    def __init__(self, modelPath, confThreshold=0.5, providers=None):
        import onnxruntime  # lazy: only needed for the GPU/ONNX backend

        self.model_path = modelPath
        self.conf_threshold = confThreshold
        if providers is None:
            providers = ["CUDAExecutionProvider", "CPUExecutionProvider"]
        self.session = onnxruntime.InferenceSession(self.model_path, providers=providers)
        self.input_name = self.session.get_inputs()[0].name
        # Map outputs BY SHAPE so Identity/Identity_N naming (and the runtime's
        # ordering) don't matter: the (…,195) tensor is the image landmarks, the
        # (…,117) tensor the world landmarks, the size-1 tensor the pose score.
        self._out_all = [o.name for o in self.session.get_outputs()]
        self._name_img = self._name_world = self._name_score = None
        for o in self.session.get_outputs():
            dims = [d for d in o.shape if isinstance(d, int) and d > 0]
            last = dims[-1] if dims else None
            total = int(np.prod(dims)) if dims else None
            if last == 39 * 5:          # 195
                self._name_img = o.name
            elif last == 39 * 3:        # 117
                self._name_world = o.name
            elif total == 1:
                self._name_score = o.name
        if not (self._name_img and self._name_world and self._name_score):
            raise RuntimeError(
                "pose-landmark ONNX outputs not recognized by shape: "
                f"{[(o.name, o.shape) for o in self.session.get_outputs()]}")

    def infer(self, bgr, det_row):
        """Run the landmark stage for one detection.

        ``det_row`` is one row of ``MPPersonDet.infer`` output:
        ``[box(4), keypoints(8 = 4x[x,y] in image px), score(1)]``.
        Returns ``(screen_landmarks, world_landmarks)`` — each a list of 33
        ``_Landmark`` — or ``None`` if the pose-presence score is too low.
        """
        h, w = bgr.shape[:2]
        kps = det_row[4:12].reshape(4, 2)

        body = _Body()
        # Detector keypoints are already in original-image PIXELS; the ROI math
        # stays in pixels (isotropic — see _detections_to_rect).
        body.pd_kps = [(float(kx), float(ky)) for kx, ky in kps]
        _detections_to_rect(body, kp_pair=(0, 1))
        _rect_transformation(body)

        crop = _warp_rect_img(body.rect_points, bgr, LM_INPUT_SIZE, LM_INPUT_SIZE)
        rgb = cv.cvtColor(crop, cv.COLOR_BGR2RGB).astype(np.float32) / 255.0
        blob = np.ascontiguousarray(rgb[np.newaxis, ...], dtype=np.float32)  # NHWC

        outs = self.session.run(
            [self._name_score, self._name_img, self._name_world],
            {self.input_name: blob})
        # The pose-presence flag is already a probability in [0, 1] (verified:
        # ~1.0 with a person in the crop, ~0.0 on blank/noise), so compare it to
        # the threshold directly — no sigmoid (matches the geaxgx reference).
        score = float(np.asarray(outs[0]).reshape(-1)[0])
        if score < self.conf_threshold:
            return None

        lm_raw = np.asarray(outs[1]).reshape(-1, 5)          # 39 x 5
        world_raw = np.asarray(outs[2]).reshape(-1, 3)       # 39 x 3

        # --- image landmarks -> normalized [0,1] in the ORIGINAL frame --------
        norm = lm_raw[:NUM_POSE_LANDMARKS, :3] / LM_INPUT_SIZE   # x,y,z in [0,1] box
        visibility = 1.0 / (1.0 + np.exp(-np.clip(lm_raw[:NUM_POSE_LANDMARKS, 3], -30, 30)))
        # Affine [0,1] box coords -> image pixels using the rotated ROI corners.
        src = np.array([(0, 0), (1, 0), (1, 1)], dtype=np.float32)
        dst = np.array(body.rect_points[1:], dtype=np.float32)
        mat = cv.getAffineTransform(src, dst)
        xy = cv.transform(norm[:, :2][np.newaxis, ...].astype(np.float32), mat)[0]
        # z stays in the box's scale (rect_w_a px), /4 for realism, then made
        # frame-normalized so it sits on roughly MediaPipe's z scale.
        z_px = norm[:, 2] * body.rect_w_a / 4.0
        screen = [
            _Landmark(x=float(xy[i, 0]) / w, y=float(xy[i, 1]) / h,
                      z=float(z_px[i]) / w, visibility=float(visibility[i]))
            for i in range(NUM_POSE_LANDMARKS)
        ]

        # --- world landmarks -> meters, hip origin; only rotation applied -----
        world_xyz = world_raw[:NUM_POSE_LANDMARKS].copy()
        sin_r, cos_r = sin(body.rotation), cos(body.rotation)
        rot = np.array([[cos_r, sin_r], [-sin_r, cos_r]], dtype=np.float32)
        world_xyz[:, :2] = world_xyz[:, :2] @ rot
        world = [
            _Landmark(x=float(world_xyz[i, 0]), y=float(world_xyz[i, 1]),
                      z=float(world_xyz[i, 2]), visibility=float(visibility[i]))
            for i in range(NUM_POSE_LANDMARKS)
        ]
        return screen, world
