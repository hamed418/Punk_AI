import type { Plan } from "@/types/subscription";

export interface ParsedDescription {
  name: string;
  shortDescription: string;
  features: string[];
  status: "draft" | "published";
}

export const parsePlanData = (plan: Plan): ParsedDescription => {
  let features: string[] = [];
  let shortDescription = plan.description || "";
  let status: "draft" | "published" = "published";
  const name = plan.name || "Pro";

  // 1. Direct features from API
  if (Array.isArray(plan.features) && plan.features.length > 0) {
    features = plan.features.filter((f) => Boolean(f && String(f).trim()));
  }

  // 2. Parse from description if stored as JSON or delimited string
  if (plan.description) {
    try {
      const parsed = JSON.parse(plan.description);
      if (typeof parsed === "object" && parsed !== null) {
        if (parsed.shortDescription) {
          shortDescription = parsed.shortDescription;
        } else if (parsed.description && parsed.description !== plan.description) {
          shortDescription = parsed.description;
        } else {
          shortDescription = "";
        }
        if (features.length === 0 && Array.isArray(parsed.features)) {
          features = parsed.features.filter((f: any) => Boolean(f && String(f).trim()));
        }
        if (parsed.status) {
          status = parsed.status;
        }
      }
    } catch {
      // Plain string: check if comma-separated or newline-separated
      if (features.length === 0) {
        if (plan.description.includes(",")) {
          features = plan.description
            .split(",")
            .map((f) => f.trim())
            .filter(Boolean);
          shortDescription = "";
        } else if (plan.description.includes("\n")) {
          features = plan.description
            .split("\n")
            .map((f) => f.trim())
            .filter(Boolean);
          shortDescription = "";
        }
      }
    }
  }

  // Clean up shortDescription if it's identical to comma-separated features
  if (features.length > 0 && shortDescription.includes(",")) {
    shortDescription = "";
  }

  return {
    name,
    shortDescription,
    features,
    status,
  };
};
