/**
 * Registry of selectable VRM avatars. Every entry is a humanoid VRM (0.x or 1.0)
 * with the full bone set (incl. fingers), so the rig in VrmAvatar.tsx drives any
 * of them unchanged — the rig captures each model's rest pose on load and is
 * model-agnostic. Files live under web/public and are served at the `src` path.
 * The switcher pill in App.tsx cycles this list (also the `v` key).
 */
export interface AvatarDef {
  /** Display label shown on the switcher pill. */
  name: string;
  /** Path served by the frontend (a file under web/public). */
  src: string;
}

export const AVATARS: AvatarDef[] = [
  { name: "Shino", src: "/avatar.vrm" }, // CC0 VRoid sample (the original default)
  { name: "Cool Alien", src: "/avatars/CoolAlien.vrm" },
  { name: "Cool Banana", src: "/avatars/CoolBanana.vrm" },
  { name: "Milk", src: "/avatars/Milk.vrm" },
  { name: "Agnes", src: "/avatars/Agnes.vrm" },
  { name: "Stitch Witch", src: "/avatars/StitchWitch.vrm" },
];
