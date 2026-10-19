import { clsx, type ClassValue } from "clsx";
import { extendTailwindMerge } from "tailwind-merge";

/**
 * The design system's named type sizes (`text-body`, `text-label`, ...) are font sizes. Without
 * telling the merger, it reads them as colours and drops the real text colour beside them
 * (a button given `text-body` lost its white label).
 */
const twMerge = extendTailwindMerge({
  extend: {
    classGroups: {
      "font-size": [
        { text: ["display", "h1", "h2", "h3", "body", "body-sm", "label", "caption", "numeral"] },
      ],
    },
  },
});

export const cn = (...inputs: ClassValue[]) => twMerge(clsx(inputs));
