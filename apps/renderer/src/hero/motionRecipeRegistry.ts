/** Local, deterministic registry for the admitted editorial motion recipes. */

export type MotionRecipeRoute = {
  componentId: string;
  fallbackComponentId: string;
};

const ROUTES: Record<string, MotionRecipeRoute> = {
  "motion-caption-emphasis-v1": { componentId: "caption-emphasis-v1", fallbackComponentId: "context-line-v1" },
  "motion-caption-emphasis-short-v1": { componentId: "caption-emphasis-v1", fallbackComponentId: "context-line-v1" },
  "motion-caption-emphasis-payoff-v1": { componentId: "caption-emphasis-v1", fallbackComponentId: "context-line-v1" },
  "motion-caption-emphasis-process-v1": { componentId: "caption-emphasis-v1", fallbackComponentId: "context-line-v1" },
  "motion-context-reveal-v1": { componentId: "context-line-v1", fallbackComponentId: "caption-emphasis-v1" },
  "motion-context-reveal-question-v1": { componentId: "context-line-v1", fallbackComponentId: "caption-emphasis-v1" },
  "motion-context-reveal-takeaway-v1": { componentId: "context-line-v1", fallbackComponentId: "caption-emphasis-v1" },
  "motion-hook-card-v1": { componentId: "hook-card-v1", fallbackComponentId: "context-line-v1" },
  "motion-hook-card-question-v1": { componentId: "hook-card-v1", fallbackComponentId: "context-line-v1" },
  "motion-hook-card-proof-v1": { componentId: "hook-card-v1", fallbackComponentId: "context-line-v1" },
  "motion-punch-card-v1": { componentId: "punch-card-v1", fallbackComponentId: "caption-emphasis-v1" },
  "motion-punch-card-result-v1": { componentId: "punch-card-v1", fallbackComponentId: "caption-emphasis-v1" },
  "motion-punch-card-reaction-v1": { componentId: "punch-card-v1", fallbackComponentId: "caption-emphasis-v1" },
  "motion-native-graphic-v1": { componentId: "motion-graphic-v1", fallbackComponentId: "context-line-v1" },
  "motion-graphic-concept-v1": { componentId: "motion-graphic-v1", fallbackComponentId: "context-line-v1" },
  "motion-graphic-data-v1": { componentId: "motion-graphic-v1", fallbackComponentId: "context-line-v1" },
  "motion-quran-challenge-v1": { componentId: "motion-graphic-v1", fallbackComponentId: "context-line-v1" },
  "motion-concat-dissolve-v1": { componentId: "concat_blur_dissolve_v1", fallbackComponentId: "concat_push_v1" },
  "motion-concat-dissolve-payoff-v1": { componentId: "concat_blur_dissolve_v1", fallbackComponentId: "concat_push_v1" },
  "motion-concat-push-v1": { componentId: "concat_push_v1", fallbackComponentId: "concat_blur_dissolve_v1" },
  "motion-concat-push-location-v1": { componentId: "concat_push_v1", fallbackComponentId: "concat_blur_dissolve_v1" },
};

export function motionRecipeRoute(recipeId: string): MotionRecipeRoute {
  const route = ROUTES[recipeId];
  if (!route) throw new Error(`unsupported production motion recipe ${recipeId}`);
  return route;
}

export function validateMotionRecipes(recipeIds: readonly string[], catalogSha256?: string): void {
  for (const recipeId of recipeIds) motionRecipeRoute(recipeId);
  if (recipeIds.length > 0 && !/^[0-9a-f]{64}$/.test(catalogSha256 ?? "")) {
    throw new Error("production motion recipes require a verified catalog fingerprint");
  }
}

