(function () {
  var board = document.getElementById("board");
  var video = document.getElementById("preview");
  var status = document.getElementById("status");
  var reviewer = document.getElementById("reviewer");
  var notes = document.getElementById("notes");
  var candidateId = window.location.hash.replace(/^#/, "") || "";
  var card = {};

  function text(parent, value) {
    var node = document.createElement("p");
    node.textContent = value;
    parent.appendChild(node);
  }

  function render(payload) {
    while (board.firstChild) {
      board.removeChild(board.firstChild);
    }
    text(board, "candidate " + payload.candidate_id + " rank " + payload.rank);
    text(board, "project " + payload.project_id);
    text(board, "source " + payload.source_asset_id);
    text(board, "artifact " + payload.artifact_id);
    text(board, "manifest " + payload.manifest_sha256);
    text(board, "duration " + payload.duration_us);
    text(board, "codecs " + payload.video_codec + " " + payload.audio_codec);
    text(board, "captions " + payload.caption_count);
    text(board, "qa " + payload.qa_set_id + " " + payload.qa_status);
    text(board, "delivery " + (payload.delivery_manifest_sha256 || "none"));
    text(board, "decision " + payload.effective_decision);
    text(board, "blockers " + (payload.blockers || []).join(" "));
    text(board, "whop deferred");
    text(board, "publishing deferred");
    (payload.typography || []).forEach(function (item) {
      text(board, "typography " + item);
    });
    (payload.emphasis || []).forEach(function (item) {
      text(board, "emphasis " + item);
    });
    (payload.history || []).forEach(function (item) {
      text(board, "history " + item.decision + " " + item.reviewer_id + " " + item.notes);
    });
    candidateId = payload.candidate_id;
    card = payload;
    video.src = "/media/final/" + candidateId;
    video.autoplay = false;
  }

  function load() {
    var path = "/api/final-review";
    if (candidateId) {
      path += "/" + candidateId;
    }
    fetch(path)
      .then(function (response) { return response.json(); })
      .then(render);
  }

  document.getElementById("decision-form").addEventListener("submit", function (event) {
    event.preventDefault();
    var decision = event.submitter ? event.submitter.getAttribute("data-decision") : "approved";
    fetch("/api/review/decisions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        subject_kind: "final",
        source_asset_id: card.source_asset_id || "",
        candidate_id: candidateId,
        artifact_id: card.artifact_id || "",
        manifest_sha256: card.manifest_sha256 || "",
        decision: decision,
        reviewer_id: reviewer.value,
        notes: notes.value,
        automated: false
      })
    }).then(function (response) {
      return response.json().then(function (payload) {
        status.textContent = response.ok ? payload.decision : payload.error;
        if (response.ok) {
          load();
        }
      });
    });
  });

  fetch("/api/final-review")
    .then(function (response) { return response.json(); })
    .then(function (payload) {
      document.body.setAttribute("data-source", payload.source_asset_id || "");
      render(payload);
    });
})();
