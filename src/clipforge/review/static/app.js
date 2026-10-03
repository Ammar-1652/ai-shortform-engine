const summary = document.querySelector("#summary");
const cards = document.querySelector("#cards");
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
    return;
  }
  for (const card of board.candidates) {
    cards.append(renderCard(board, card));
  }
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
