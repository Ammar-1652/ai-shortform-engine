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
  return node;
}

function shown(value) {
  if (value == null || value === "") {
    return "unavailable";
  }
  return String(value);
}

function decisionLabel(decision) {
  if (!decision) {
    return "none";
  }
  return decision.decision + " by " + decision.reviewer_id + " at " + decision.created_at;
}

function renderBoard(board) {
  summary.replaceChildren();
  line(summary, "stage hero");
  line(summary, "source " + board.source_asset_id);
  line(summary, "project " + board.project_id);
  line(summary, "integrity " + board.integrity);
  drafts.replaceChildren();
  if (board.status === "empty" || !board.drafts || board.drafts.length === 0) {
    line(drafts, "No current Hero drafts are stored for this source.");
    return;
  }
  line(summary, "hero set " + board.hero_set_id);
  line(summary, "artifact " + board.artifact_id);
  line(summary, "manifest " + board.manifest_sha256);
  line(summary, "candidate set " + board.candidate_set_artifact_id);
  line(summary, "candidate set sha " + board.candidate_set_sha256);
  line(summary, "source sha " + board.source_sha256);
  line(summary, "profile " + board.profile_id + " " + board.profile_fingerprint);
  line(summary, "whisperx " + shown(board.whisperx_version));
  line(summary, "alignment model " + shown(board.alignment_model));
  line(summary, "checkpoint sha " + shown(board.alignment_checkpoint_sha256));
  line(summary, "alignment language " + shown(board.alignment_language));
  line(summary, "motion library " + shown(board.motion_library_version));
  for (const draft of board.drafts) {
    drafts.append(renderDraft(board, draft));
  }
}

function renderDraft(board, draft) {
  const article = document.createElement("article");
  line(article, "rank " + draft.rank);
  line(article, "candidate " + draft.candidate_id);
  line(article, "source " + draft.source_asset_id);
  line(article, "project " + draft.project_id);
  const video = document.createElement("video");
  video.controls = true;
  video.preload = "metadata";
  video.playsInline = true;
  video.src = draft.preview_url;
  article.append(video);
  const meta = document.createElement("div");
  meta.className = "meta";
  line(meta, "hero set " + draft.hero_set_id);
  line(meta, "artifact " + draft.artifact_id);
  line(meta, "manifest " + draft.manifest_sha256);
  line(meta, "plan " + draft.plan_id);
  line(meta, "plan sha " + draft.plan_sha256);
  line(meta, "alignment " + draft.alignment_id);
  line(meta, "alignment sha " + draft.alignment_sha256);
  line(meta, "whisperx " + shown(draft.whisperx_version));
  line(meta, "model " + shown(draft.alignment_model));
  line(meta, "checkpoint sha " + shown(draft.alignment_checkpoint_sha256));
  line(meta, "language " + shown(draft.alignment_language));
  line(meta, "timing " + shown(draft.timing_quality));
  line(meta, "source range " + draft.source_start_us + "–" + draft.source_end_us + " us");
  line(meta, "duration " + draft.output_duration_us + " us");
  line(meta, draft.width + "×" + draft.height);
  line(meta, "fps " + draft.fps_numerator + "/" + draft.fps_denominator);
  line(meta, "video " + shown(draft.video_codec));
  line(meta, "pixel " + shown(draft.pixel_format));
  line(meta, "audio " + shown(draft.audio_codec));
  line(meta, "sample rate " + shown(draft.audio_sample_rate));
  line(meta, "motion library " + shown(draft.motion_library_version));
  line(meta, "words " + draft.word_count);
  line(meta, "hero decision " + decisionLabel(draft.current_decision));
  const motion = document.createElement("ul");
  motion.className = "motion";
  const settings = draft.motion_settings || [];
  if (settings.length === 0) {
    const item = document.createElement("li");
    text(item, "motion settings unavailable");
    motion.append(item);
  } else {
    for (const item of settings) {
      const entry = document.createElement("li");
      text(
        entry,
        item.purpose + " " + item.component_id + " " + item.output_start_us + "-" + item.output_end_us,
      );
      motion.append(entry);
    }
  }
  meta.append(motion);
  article.append(meta);
  const words = document.createElement("ol");
  words.className = "words";
  for (const word of draft.words || []) {
    const entry = document.createElement("li");
    text(
      entry,
      word.text +
        " source " +
        word.source_start_us +
        "-" +
        word.source_end_us +
        " output " +
        word.output_start_us +
        "-" +
        word.output_end_us +
        " frames " +
        word.output_start_frame +
        "-" +
        word.output_end_frame_exclusive,
    );
    words.append(entry);
  }
  article.append(words);
  const history = document.createElement("ol");
  history.className = "history";
  for (const item of draft.history || []) {
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
    input.name = "hero-decision-" + draft.candidate_id;
    input.value = name;
    label.append(input, document.createTextNode(" " + name + " "));
    choices.append(label);
  }
  const save = document.createElement("button");
  save.type = "button";
  text(save, "Save hero decision");
  save.addEventListener("click", () => saveDecision(board, draft, choices, reviewer, notes));
  article.append(reviewer, notes, choices, save);
  return article;
}

async function saveDecision(board, draft, choices, reviewer, notes) {
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
      preview_set_id: board.hero_set_id,
      hero_set_id: board.hero_set_id,
      manifest_sha256: board.manifest_sha256,
      source_sha256: board.source_sha256,
      candidate_id: draft.candidate_id,
      plan_id: draft.plan_id,
      plan_sha256: draft.plan_sha256,
      alignment_id: draft.alignment_id,
      alignment_sha256: draft.alignment_sha256,
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

async function loadBoard() {
  const response = await fetch("/api/hero-review");
  const payload = await response.json();
  if (!response.ok) {
    text(status, payload.error || "The Hero set is not reviewable.");
    drafts.replaceChildren();
    return;
  }
  renderBoard(payload);
}

loadBoard().catch((error) => {
  text(status, error instanceof Error ? error.message : "The Hero review page could not load.");
});
