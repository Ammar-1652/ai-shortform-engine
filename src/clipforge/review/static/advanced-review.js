const summary = document.querySelector("#summary");
const drafts = document.querySelector("#drafts");
const status = document.querySelector("#status");

function text(parent, value) {
  parent.textContent = value == null ? "" : String(value);
}

function line(parent, value) {
  const node = document.createElement("p");
  text(node, value);
  parent.append(node);
}

function renderBoard(board) {
  summary.replaceChildren();
  drafts.replaceChildren();
  line(summary, "stage advanced");
  line(summary, "source " + board.source_asset_id);
  line(summary, "project " + board.project_id);
  line(summary, "reframing " + board.reframing_strategy);
  line(summary, "profile " + (board.profile_id || "none"));
  line(summary, "policies " + ((board.policy_ids || []).join(" ") || "none"));
  line(summary, "qa " + (board.qa_status || "none"));
  line(summary, "technical " + (board.technical_status || "none"));
  line(summary, "campaign " + (board.campaign_status || "none"));
  if (!board.drafts || board.drafts.length === 0) {
    line(drafts, "No current advanced Hero drafts are stored.");
    return;
  }
  line(summary, "advanced set " + board.advanced_set_id);
  line(summary, "artifact " + board.artifact_id);
  for (const draft of board.drafts) {
    drafts.append(renderDraft(board, draft));
  }
}

function renderDraft(board, draft) {
  const article = document.createElement("article");
  line(article, "candidate " + draft.candidate_id);
  line(article, "rank " + draft.rank);
  const video = document.createElement("video");
  video.controls = true;
  video.preload = "metadata";
  video.playsInline = true;
  video.src = draft.preview_url;
  article.append(video);
  for (const item of draft.broll || []) {
    line(
      article,
      "broll " + item.display_name + " " + item.kind + " " + item.rights_status + " " + item.output_start_us + "-" + item.output_end_us + " in " + item.source_in_us + " " + item.layer_name,
    );
  }
  for (const item of draft.sfx || []) {
    line(
      article,
      "sfx " + item.display_name + " " + item.rights_status + " " + item.role + " " + item.gain_db + "dB " + item.output_start_us + "-" + item.output_end_us,
    );
  }
  for (const item of draft.typography || []) {
    line(
      article,
      "type " + item.component_id + " " + item.purpose + " " + item.text + " " + item.output_start_us + "-" + item.output_end_us + " " + item.style_id,
    );
  }
  for (const item of draft.diagrams || []) {
    line(
      article,
      "diagram " + item.component_id + " " + item.kind + " " + item.left_label + " " + item.left_value + " " + item.right_label + " " + item.right_value,
    );
  }
  for (const item of draft.emphasis || []) {
    line(
      article,
      "emphasis " + item.text + " " + item.word_id + " " + item.output_start_frame + "-" + item.output_end_frame_exclusive + " " + item.rule_id,
    );
  }
  const history = document.createElement("ol");
  history.className = "history";
  for (const item of draft.history || []) {
    const entry = document.createElement("li");
    const scope = item.current_artifact ? "current artifact" : "older artifact";
    text(entry, item.decision + " by " + item.reviewer_id + " (" + scope + ") " + (item.notes || ""));
    history.append(entry);
  }
  article.append(history);
  line(article, "effective decision " + (draft.current_decision || "none"));
  const reviewer = document.createElement("input");
  reviewer.placeholder = "reviewer id";
  const notes = document.createElement("textarea");
  notes.placeholder = "notes";
  const choices = document.createElement("div");
  for (const name of ["approved", "rejected", "changes_requested"]) {
    const label = document.createElement("label");
    const input = document.createElement("input");
    input.type = "radio";
    input.name = "advanced-decision-" + draft.candidate_id;
    input.value = name;
    label.append(input, document.createTextNode(" " + name + " "));
    choices.append(label);
  }
  const save = document.createElement("button");
  save.type = "button";
  text(save, "Save advanced decision");
  save.addEventListener("click", () => saveDecision(board, draft, reviewer, notes, choices));
  article.append(reviewer, notes, choices, save);
  return article;
}

async function saveDecision(board, draft, reviewer, notes, choices) {
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
      preview_set_id: board.advanced_set_id,
      hero_set_id: draft.hero_set_id,
      manifest_sha256: board.manifest_sha256,
      source_sha256: board.source_sha256,
      candidate_id: draft.candidate_id,
      plan_id: draft.plan_id,
      plan_sha256: draft.plan_sha256,
      alignment_id: draft.alignment_id,
      alignment_sha256: draft.alignment_sha256,
      advanced_set_id: board.advanced_set_id,
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
  text(status, "Saved advanced " + payload.decision);
  await loadBoard();
}

async function loadBoard() {
  const response = await fetch("/api/advanced-hero-review");
  const payload = await response.json();
  if (!response.ok) {
    text(status, payload.error || "The advanced set is not reviewable.");
    return;
  }
  renderBoard(payload);
}

loadBoard().catch((error) => {
  text(status, error instanceof Error ? error.message : "The advanced review page could not load.");
});
