// ARIA — Icon set (lucide-style, hand-tuned for the dashboard)

import React from "react";
import type { IconName } from "../types";

interface IconBaseProps {
  d?: string;
  size?: number;
  stroke?: number;
  fill?: string;
  style?: React.CSSProperties;
  className?: string;
  children?: React.ReactNode;
}

export function Icon({
  d,
  size = 16,
  stroke = 1.6,
  fill = "none",
  style,
  className,
  children,
}: IconBaseProps) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill={fill}
      stroke="currentColor"
      strokeWidth={stroke}
      strokeLinecap="round"
      strokeLinejoin="round"
      style={style}
      className={className}
    >
      {d && <path d={d} />}
      {children}
    </svg>
  );
}

export type IconProps = Omit<IconBaseProps, "d" | "children">;

const icons: Record<IconName, (p: IconProps) => React.ReactElement> = {
  mic: (p) => (
    <Icon {...p}>
      <rect x="9" y="2" width="6" height="12" rx="3" />
      <path d="M5 11a7 7 0 0 0 14 0M12 18v3M8 21h8" />
    </Icon>
  ),
  brain: (p) => (
    <Icon {...p}>
      <path d="M9 4a3 3 0 0 0-3 3v.5A3 3 0 0 0 4 10v2a3 3 0 0 0 2 2.8V17a3 3 0 0 0 3 3 3 3 0 0 0 3-3V4a0 0 0 0 0 0 0 3 3 0 0 0-3 0z" />
      <path d="M15 4a3 3 0 0 1 3 3v.5A3 3 0 0 1 20 10v2a3 3 0 0 1-2 2.8V17a3 3 0 0 1-3 3 3 3 0 0 1-3-3V7" />
    </Icon>
  ),
  compass: (p) => (
    <Icon {...p}>
      <circle cx="12" cy="12" r="9" />
      <polygon
        points="15.5,8.5 11,10 9.5,15.5 14,14"
        fill="currentColor"
        stroke="none"
        opacity="0.85"
      />
    </Icon>
  ),
  heart: (p) => (
    <Icon {...p}>
      <path d="M4 13l3-3 2 4 3-7 2 4h6" />
      <path
        d="M12 21s-7-4.35-9-9a5 5 0 0 1 9-3 5 5 0 0 1 9 3c-2 4.65-9 9-9 9z"
        opacity="0.35"
      />
    </Icon>
  ),
  flame: (p) => (
    <Icon {...p}>
      <path d="M12 2c1 4 4 5 4 9a4 4 0 0 1-8 0c0-2 1-3 2-4 .5 1 1 2 0 3" />
      <path d="M7 14a5 5 0 0 0 10 0" />
    </Icon>
  ),
  doc: (p) => (
    <Icon {...p}>
      <path d="M7 3h7l5 5v13a1 1 0 0 1-1 1H7a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1z" />
      <path d="M14 3v5h5M9 13h6M9 17h6" />
    </Icon>
  ),
  bolt: (p) => (
    <Icon {...p}>
      <polygon
        points="13,2 4,14 11,14 10,22 20,10 13,10"
        fill="currentColor"
        stroke="currentColor"
      />
    </Icon>
  ),
  play: (p) => (
    <Icon {...p}>
      <polygon points="6,4 20,12 6,20" fill="currentColor" stroke="none" />
    </Icon>
  ),
  pause: (p) => (
    <Icon {...p}>
      <rect x="6" y="4" width="4" height="16" fill="currentColor" stroke="none" />
      <rect x="14" y="4" width="4" height="16" fill="currentColor" stroke="none" />
    </Icon>
  ),
  stop: (p) => (
    <Icon {...p}>
      <rect x="5" y="5" width="14" height="14" fill="currentColor" stroke="none" />
    </Icon>
  ),
  check: (p) => <Icon d="M5 12l4 4 10-11" {...p} />,
  x: (p) => (
    <Icon {...p}>
      <path d="M6 6l12 12M18 6L6 18" />
    </Icon>
  ),
  alert: (p) => (
    <Icon {...p}>
      <path d="M12 3l10 18H2L12 3z" />
      <path d="M12 10v5M12 18v.5" />
    </Icon>
  ),
  ambulance: (p) => (
    <Icon {...p}>
      <rect x="2" y="8" width="13" height="9" rx="1" />
      <path d="M15 11h4l2 3v3h-6" />
      <circle cx="6" cy="18" r="1.8" />
      <circle cx="17" cy="18" r="1.8" />
      <path d="M7 12.5h3M8.5 11v3" />
    </Icon>
  ),
  police: (p) => (
    <Icon {...p}>
      <path d="M12 3l8 3v5c0 5-3.5 8-8 10-4.5-2-8-5-8-10V6l8-3z" />
      <path d="M9 12l2 2 4-4" />
    </Icon>
  ),
  pin: (p) => (
    <Icon {...p}>
      <path d="M12 22s7-6 7-12a7 7 0 0 0-14 0c0 6 7 12 7 12z" />
      <circle cx="12" cy="10" r="2.5" />
    </Icon>
  ),
  cross: (p) => (
    <Icon {...p}>
      <rect x="9" y="3" width="6" height="18" rx="1" fill="currentColor" stroke="none" />
      <rect x="3" y="9" width="18" height="6" rx="1" fill="currentColor" stroke="none" />
    </Icon>
  ),
  external: (p) => (
    <Icon {...p}>
      <path d="M14 4h6v6M20 4l-9 9M10 6H5a1 1 0 0 0-1 1v12a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-5" />
    </Icon>
  ),
  spinner: (p) => (
    <Icon {...p}>
      <path d="M12 3a9 9 0 0 1 9 9" />
    </Icon>
  ),
  circle: (p) => (
    <Icon {...p}>
      <circle cx="12" cy="12" r="9" />
    </Icon>
  ),
  arrowRight: (p) => <Icon d="M5 12h14M13 6l6 6-6 6" {...p} />,
};

export default icons;
