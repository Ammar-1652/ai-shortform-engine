(function () {
  var selected = null;

  function textLine(parent, value) {
    var line = document.createElement("p");
    line.textContent = value;
    parent.appendChild(line);
  }

  function metricText(value) {
    if (value === null || value === undefined) {
      return "not reported";
    }
    return String(value);
  }

  function clear(node) {
    while (node.firstChild) {
      node.removeChild(node.firstChild);
    }
  }

  function renderCard(parent, card) {
    var box = document.createElement("div");
    box.className = "card";
    textLine(box, "outcome " + card.outcome_id);
    textLine(box, "platform " + card.platform + " window " + card.measurement_window);
    textLine(box, "artifact " + card.artifact_id + " source " + card.source_asset_id);
    textLine(box, "artifact availability " + card.artifact_available);
    textLine(box, "duration " + metricText(card.duration_us));
    textLine(box, "qa " + metricText(card.qa_status) + " policy " + card.qa_policy);
    textLine(box, "import profile " + card.import_profile_id);
    var names = Object.keys(card.metrics);
    for (var index = 0; index < names.length; index += 1) {
      var name = names[index];
      textLine(box, name + " " + metricText(card.metrics[name]));
    }
    textLine(
      box,
      "metric coverage reported " + card.metric_coverage.reported + " missing " + card.metric_coverage.missing
    );
    var reviews = card.review_history || [];
    if (!reviews.length) {
      textLine(box, "review history none");
    }
    for (var reviewIndex = 0; reviewIndex < reviews.length; reviewIndex += 1) {
      var review = reviews[reviewIndex];
      textLine(box, "review " + review.decision + " by " + review.reviewer_id);
    }
    if (card.labels) {
      textLine(box, "hook " + card.labels.hook_type);
      textLine(box, "notes " + (card.label_notes || ""));
    } else {
      textLine(box, "labels none");
    }
    var history = card.label_history || [];
    textLine(box, "label history " + (history.length ? history.join(" ") : "none"));
    var warnings = card.warnings || [];
    for (var warningIndex = 0; warningIndex < warnings.length; warningIndex += 1) {
      var warning = document.createElement("p");
      warning.className = "warning";
      warning.textContent = warnings[warningIndex];
      box.appendChild(warning);
    }
    var button = document.createElement("button");
    button.type = "button";
    button.textContent = "Select " + card.outcome_id;
    button.addEventListener("click", function () {
      selected = card;
      renderDetail(card);
    });
    box.appendChild(button);
    parent.appendChild(box);
  }

  function renderDetail(card) {
    var detail = document.getElementById("detail");
    clear(detail);
    renderCard(detail, card);
    var history = document.getElementById("label-history");
    clear(history);
    textLine(history, "effective label " + metricText(card.effective_label_set_id));
    textLine(history, "notes " + (card.label_notes || ""));
  }

  function renderComparison(documentPayload) {
    var host = document.getElementById("comparison");
    clear(host);
    textLine(host, documentPayload.note);
    textLine(host, "status " + documentPayload.status);
    textLine(host, "observations " + documentPayload.observation_count);
    var sources = documentPayload.provenance && documentPayload.provenance.source_asset_ids;
    textLine(host, "sources " + ((sources && sources.length) ? sources.join(" ") : "none"));
    var cohorts = documentPayload.cohorts || [];
    if (!cohorts.length) {
      textLine(host, "insufficient_evidence");
    }
    for (var index = 0; index < cohorts.length; index += 1) {
      var cohort = cohorts[index];
      var item = cohort.aggregate;
      textLine(host, "cohort " + cohort.key + " sample " + item.sample_count);
      textLine(host, "views denominator " + item.views_count + "/" + item.sample_count);
      textLine(host, "missing views " + item.missing_views);
      textLine(host, "missing completion rate " + item.missing_completion_rate);
    }
  }

  function load() {
    fetch("api/analytics/overview")
      .then(function (response) {
        if (!response.ok) {
          throw new Error("overview failed");
        }
        return response.json();
      })
      .then(function (payload) {
        document.getElementById("status").textContent = "Project " + payload.project_id;
        var host = document.getElementById("outcomes");
        clear(host);
        var cards = payload.outcomes || [];
        if (!cards.length) {
          textLine(host, "No outcomes are stored.");
        }
        for (var index = 0; index < cards.length; index += 1) {
          renderCard(host, cards[index]);
        }
        if (cards.length) {
          selected = cards[0];
          renderDetail(cards[0]);
        }
        renderComparison(payload.comparison);
      })
      .catch(function () {
        document.getElementById("status").textContent = "Analytics evidence could not be loaded.";
      });
  }

  document.getElementById("label-form").addEventListener("submit", function (event) {
    event.preventDefault();
    var message = document.getElementById("label-message");
    if (!selected) {
      message.textContent = "Select an outcome before saving labels.";
      return;
    }
    var topics = document.getElementById("topics").value.trim();
    var topicTags = [];
    if (topics) {
      var parts = topics.split(" ");
      for (var topicIndex = 0; topicIndex < parts.length; topicIndex += 1) {
        if (parts[topicIndex]) {
          topicTags.push(parts[topicIndex]);
        }
      }
    }
    var body = {
      project_id: selected.project_id,
      source_asset_id: selected.source_asset_id,
      artifact_id: selected.artifact_id,
      outcome_id: selected.outcome_id,
      snapshot_id: selected.snapshot_id,
      expected_label_set_id: selected.effective_label_set_id,
      expected_artifact_sha256: selected.artifact_sha256,
      reviewer_id: document.getElementById("reviewer").value,
      notes: document.getElementById("notes").value,
      labels: {
        hook_type: document.getElementById("hook").value || "unknown",
        topic_tags: topicTags,
        cta: document.getElementById("cta").value || "unknown",
        format_tag: document.getElementById("format-tag").value || "unknown",
        audience_tag: document.getElementById("audience").value || "unknown"
      }
    };
    fetch("api/analytics/labels", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body)
    })
      .then(function (response) {
        return response.json().then(function (payload) {
          return { ok: response.ok, payload: payload };
        });
      })
      .then(function (result) {
        if (!result.ok) {
          message.textContent = result.payload.error || "label save failed";
          return;
        }
        message.textContent = "saved " + result.payload.label_set_id;
        load();
      })
      .catch(function () {
        message.textContent = "label save failed";
      });
  });

  document.getElementById("compare").addEventListener("click", function () {
    var dimension = document.getElementById("dimension").value;
    fetch("api/analytics/comparison?dimension=" + encodeURIComponent(dimension))
      .then(function (response) {
        return response.json();
      })
      .then(renderComparison)
      .catch(function () {
        document.getElementById("comparison").textContent = "comparison failed";
      });
  });

  load();
})();
