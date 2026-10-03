const summary = document.querySelector("#summary");
const cards = document.querySelector("#cards");
const hero = document.querySelector("#hero");
const status = document.querySelector("#status");

function text(parent, value) {
  parent.textContent = value == null ? "" : String(value);
}

function line(parent, value) {
  const node = document.createElement("p");
  text(node, value);
  parent.append(node);
  return node;
}

function decisionLabel(decision) {
  if (!decision) {
    return "none";
  }
  return decision.decision + " by " + decision.reviewer_id + " at " + decision.created_at;
}

function renderBoard(board) {
  summary.replaceChildren();
  line(summary, "stage rough");
  line(summary, "source " + board.source_asset_id);
  line(summary, "project " + board.project_id);
  line(summary, "preview set " + board.preview_set_id);
  line(summary, "manifest " + String(board.manifest_sha256).slice(0, 12));
  line(summary, "mining " + board.mining_id);
  line(summary, "candidates " + board.candidate_count);
  line(summary, "integrity " + board.integrity);
  cards.replaceChildren();
  if (!board.candidates || board.candidates.length === 0) {
    line(cards, "No candidates were selected in the current candidate set.");
  } else {
    for (const card of board.candidates) {
      cards.append(renderCard(board, card));
    }
  }
  renderHero(board);
}

function renderHero(board) {
  hero.replaceChildren();
  if (!board.hero) {
    line(hero, "No Hero draft is stored for this source.");
    return;
  }
  if (board.hero.status !== "ready") {
    line(hero, "Hero draft is not reviewable.");
    return;
  }
  line(hero, "stage hero");
  line(hero, "hero set " + board.hero.hero_set_id);
  line(hero, "alignment " + board.hero.alignment_model + " " + board.hero.whisperx_version);
  line(hero, "profile " + String(board.hero.profile_fingerprint).slice(0, 12));
  for (const draft of board.hero.drafts || []) {
    hero.append(renderHeroDraft(board, draft));
  }
}

function renderHeroDraft(board, draft) {
  const article = document.createElement("article");
  line(article, "stage hero");
  line(article, "candidate " + draft.candidate_id);
  line(article, "source " + draft.source_asset_id);
  const video = document.createElement("video");
  video.controls = true;
  video.preload = "metadata";
  video.src = draft.preview_url;
  article.append(video);
  const meta = document.createElement("div");
  meta.className = "meta";
  line(meta, "enabled by approval " + draft.approval_review_id + " " + draft.approval_decision);
  line(meta, "reviewer " + draft.approval_reviewer_id);
  line(meta, "alignment " + draft.alignment_quality + " " + draft.alignment_model);
  line(meta, "whisperx " + draft.whisperx_version);
  line(meta, "profile " + draft.profile_fingerprint);
  line(meta, "duration " + draft.duration_us + " us");
  line(meta, draft.width + "×" + draft.height + " at " + draft.fps_numerator + "/" + draft.fps_denominator);
  line(meta, draft.video_codec + " / " + draft.audio_codec + " / " + draft.pixel_format);
  line(meta, "captions " + draft.caption_count);
  line(meta, "hero decision " + decisionLabel(draft.current_decision));
  article.append(meta);
  const reviewer = document.createElement("input");
  reviewer.placeholder = "reviewer id";
  const notes = document.createElement("textarea");
  notes.rows = 3;
  notes.placeholder = "notes";
  const choices = document.createElement("div");
  for (const name of ["approved", "rejected", "changes_requested"]) {
    const label = document.createElement("label");
    const input = document.createElement("input");
    input.type = "radio";
    input.name = "hero-decision-" + draft.candidate_id;
    input.value = name;
    label.append(input, document.createTextNode(" " + name + " "));
    choices.append(label);
  }
  const save = document.createElement("button");
  save.type = "button";
  text(save, "Save hero decision");
  save.addEventListener("click", () => saveHeroDecision(board, draft, choices, reviewer, notes));
  article.append(reviewer, notes, choices, save);
  return article;
}

async function saveHeroDecision(board, draft, choices, reviewer, notes) {
  const selected = choices.querySelector("input:checked");
  if (!selected) {
    text(status, "Choose approved, rejected, or changes requested.");
    return;
  }
  const response = await fetch("/api/review/decisions", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      source_asset_id: board.source_asset_id,
      project_id: board.project_id,
      artifact_id: board.hero.artifact_id,
      preview_set_id: board.hero.hero_set_id,
      hero_set_id: board.hero.hero_set_id,
      manifest_sha256: board.hero.manifest_sha256,
      source_sha256: board.hero.source_sha256,
      plan_id: draft.plan_id,
      plan_sha256: draft.plan_sha256,
      alignment_id: draft.alignment_id,
      alignment_sha256: draft.alignment_sha256,
      candidate_id: draft.candidate_id,
      subject_kind: "hero",
      decision: selected.value,
      reviewer_id: reviewer.value,
      notes: notes.value,
    }),
  });
  const payload = await response.json();
  if (!response.ok) {
    text(status, payload.error || "The decision was not saved.");
    return;
  }
  text(status, "Saved hero " + payload.decision + " for " + payload.candidate_id);
  await loadBoard();
}

function renderCard(board, card) {
  const article = document.createElement("article");
  line(article, "rank " + card.rank);
  line(article, "candidate " + card.candidate_id);
  const video = document.createElement("video");
  video.controls = true;
  video.preload = "metadata";
  video.src = card.preview_url;
  article.append(video);
  const meta = document.createElement("div");
  meta.className = "meta";
  line(meta, "source " + card.source_start_us + "–" + card.source_end_us + " us");
  line(meta, "duration " + card.output_duration_us + " us");
  line(meta, "frames " + card.output_frame_count);
  line(meta, "captions " + card.caption_count);
  line(meta, "timing " + card.timing_quality);
  line(meta, card.width + "×" + card.height + " at " + card.fps_numerator + "/" + card.fps_denominator);
  line(meta, card.video_codec + " / " + card.audio_codec + " / " + card.pixel_format);
  line(meta, "duration error " + card.duration_error_us + " us");
  line(meta, "quality score " + card.quality_score + " (" + card.quality_score_label + ")");
  line(
    meta,
    "edit opportunity score " + card.edit_opportunity_score + " (" + card.edit_opportunity_score_label + ")",
  );
  line(meta, "current decision " + decisionLabel(card.current_decision));
  article.append(meta);
  const history = document.createElement("ol");
  history.className = "history";
  for (const item of card.history || []) {
    const entry = document.createElement("li");
    const scope = item.current_artifact ? "current artifact" : "older artifact";
    text(entry, decisionLabel(item) + " (" + scope + ") " + (item.notes || ""));
    history.append(entry);
  }
  article.append(history);
  const reviewer = document.createElement("input");
  reviewer.placeholder = "reviewer id";
  const notes = document.createElement("textarea");
  notes.rows = 3;
  notes.placeholder = "notes";
  const choices = document.createElement("div");
  for (const name of ["approved", "rejected", "changes_requested"]) {
    const label = document.createElement("label");
    const input = document.createElement("input");
    input.type = "radio";
    input.name = "decision-" + card.candidate_id;
    input.value = name;
    label.append(input, document.createTextNode(" " + name + " "));
    choices.append(label);
  }
  const save = document.createElement("button");
  save.type = "button";
  text(save, "Save decision");
  save.addEventListener("click", () => saveDecision(board, card, choices, reviewer, notes));
  article.append(reviewer, notes, choices, save);
  return article;
}

async function saveDecision(board, card, choices, reviewer, notes) {
  const selected = choices.querySelector("input:checked");
  if (!selected) {
    text(status, "Choose approved, rejected, or changes requested.");
    return;
  }
  const response = await fetch("/api/review/decisions", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      source_asset_id: board.source_asset_id,
      project_id: board.project_id,
      artifact_id: board.artifact_id,
      preview_set_id: board.preview_set_id,
      manifest_sha256: board.manifest_sha256,
      candidate_id: card.candidate_id,
      decision: selected.value,
      reviewer_id: reviewer.value,
      notes: notes.value,
    }),
  });
  const payload = await response.json();
  if (!response.ok) {
    text(status, payload.error || "The decision was not saved.");
    return;
  }
  text(status, "Saved " + payload.decision + " for " + payload.candidate_id);
  await loadBoard();
}

async function loadBoard() {
  const response = await fetch("/api/review");
  const payload = await response.json();
  if (!response.ok) {
    text(status, payload.error || "The preview set is not reviewable.");
    return;
  }
  renderBoard(payload);
}

loadBoard().catch((error) => {
  text(status, error instanceof Error ? error.message : "The review page could not load.");
});
