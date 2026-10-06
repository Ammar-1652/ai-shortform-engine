(function () {
  var board = document.getElementById("board");

  function text(parent, value) {
    var row = document.createElement("p");
    row.textContent = value == null ? "" : String(value);
    parent.appendChild(row);
  }

  function clear(node) {
    while (node.firstChild) {
      node.removeChild(node.firstChild);
    }
  }

  function renderCampaign(payload) {
    var card = document.createElement("section");
    card.className = "card";
    text(card, "campaign " + payload.campaign_id);
    text(card, "title " + payload.title);
    text(card, "policy " + payload.policy_id + " " + payload.policy_fingerprint);
    text(card, "language " + payload.language);
    text(card, "alignment " + payload.alignment);
    text(card, "narration " + payload.narration);
    text(card, "voicestudio " + payload.voicestudio);
    text(card, "publishing " + payload.publishing);
    text(card, "whop_live " + payload.whop_live);
    text(card, "envato " + payload.envato);
    var rules = payload.policy_rules || [];
    for (var ruleIndex = 0; ruleIndex < rules.length; ruleIndex += 1) {
      var rule = rules[ruleIndex];
      text(card, "rule " + rule.rule_id + " " + rule.outcome + " " + rule.name);
      text(card, rule.description);
    }
    var sources = payload.sources || [];
    for (var index = 0; index < sources.length; index += 1) {
      renderSource(card, sources[index]);
    }
    var records = payload.envato_records || [];
    for (var recordIndex = 0; recordIndex < records.length; recordIndex += 1) {
      renderEnvato(card, records[recordIndex]);
    }
    board.appendChild(card);
    loadRuns(payload.campaign_id, card);
    loadPolicy(payload.campaign_id, card);
    loadAcquisitions(payload.campaign_id, card);
    loadProductions(payload.campaign_id, card);
    loadWhop(payload.campaign_id, card);
    loadEnvato(payload.campaign_id, card);
    loadAssets(payload.campaign_id, card);
  }

  function loadWhop(campaignId, card) {
    fetch("/api/campaigns/" + campaignId + "/whop")
      .then(function (response) {
        return response.json();
      })
      .then(function (payload) {
        text(card, "whop_status " + payload.status);
        text(card, "snapshot_fingerprint " + payload.snapshot_fingerprint);
        text(card, "whop_policy " + payload.policy_state);
        text(card, "whop_live " + payload.whop_live);
        var sources = payload.sources || [];
        for (var index = 0; index < sources.length; index += 1) {
          var source = sources[index];
          text(card, "whop_source " + source.source_id + " " + source.display_name);
          text(card, "whop_rights " + source.rights_state + " " + source.policy_state);
        }
      });
  }

  function loadEnvato(campaignId, card) {
    fetch("/api/campaigns/" + campaignId + "/envato")
      .then(function (response) {
        return response.json();
      })
      .then(function (payload) {
        text(card, "envato_state " + payload.envato);
        var requests = payload.requests || [];
        for (var index = 0; index < requests.length; index += 1) {
          var request = requests[index];
          text(card, "envato_request " + request.request_id + " " + request.query);
          text(card, "item_page_url " + request.item_page_url);
          text(card, "direct_download_url " + request.direct_download_url);
          text(card, "download_status " + request.download_status);
          var deferred = request.deferred_filters || {};
          var names = Object.keys(deferred);
          for (var filterIndex = 0; filterIndex < names.length; filterIndex += 1) {
            text(card, "deferred " + names[filterIndex] + " " + deferred[names[filterIndex]]);
          }
        }
      });
  }

  function loadAssets(campaignId, card) {
    fetch("/api/campaigns/" + campaignId + "/assets")
      .then(function (response) {
        return response.json();
      })
      .then(function (payload) {
        var assets = payload.assets || [];
        text(card, "assets " + assets.length);
        for (var index = 0; index < assets.length; index += 1) {
          var asset = assets[index];
          text(card, "asset " + asset.asset_id + " " + asset.rights_status);
          text(card, "asset_sha256 " + asset.sha256);
          text(card, "asset_bytes " + asset.byte_size);
          text(card, "asset_path " + asset.relative_path);
          text(card, "license_evidence " + asset.license_evidence);
          text(card, "asset_renderable " + asset.renderable + " " + asset.failure_reason);
          if (asset.probe) {
            text(card, "asset_probe " + asset.probe.video_codec + " " + asset.probe.width + " " + asset.probe.height);
            text(card, "asset_frame_rate " + asset.probe.frame_rate);
          }
        }
      });
  }

  function loadProductions(campaignId, card) {
    fetch("/api/campaigns/" + campaignId + "/productions")
      .then(function (response) {
        return response.json();
      })
      .then(function (payload) {
        var rows = payload.productions || [];
        text(card, "productions " + rows.length);
        for (var index = 0; index < rows.length; index += 1) {
          loadProduction(rows[index].run_id, card);
        }
      });
  }

  function loadProduction(runId, card) {
    fetch("/api/campaign-productions/" + runId)
      .then(function (response) {
        return response.json();
      })
      .then(function (payload) {
        text(card, "production " + payload.run_id + " " + payload.status + " " + payload.reason_code);
        text(card, "language " + payload.language);
        text(card, "cache_hit " + payload.cache_hit);
        var sources = payload.sources || [];
        for (var index = 0; index < sources.length; index += 1) {
          var source = sources[index];
          text(
            card,
            "produced " +
              source.source_id +
              " " +
              source.status +
              " review " +
              source.review_decision +
              " qa " +
              source.qa_set_id +
              " narration " +
              source.narration_status
          );
          text(card, "delivery " + source.delivery_relative);
          text(card, "media_sha256 " + source.final_media_sha256);
        }
      });
  }

  function loadPolicy(campaignId, card) {
    fetch("/api/campaigns/" + campaignId + "/policy")
      .then(function (response) {
        return response.json();
      })
      .then(function (payload) {
        text(card, "policy_fingerprint " + payload.policy_fingerprint);
      });
  }

  function loadAcquisitions(campaignId, card) {
    fetch("/api/campaigns/" + campaignId + "/acquisitions")
      .then(function (response) {
        return response.json();
      })
      .then(function (payload) {
        var rows = payload.acquisitions || [];
        text(card, "acquisitions " + rows.length);
        for (var index = 0; index < rows.length; index += 1) {
          loadAcquisition(rows[index].acquisition_id, card);
        }
      });
  }

  function loadAcquisition(acquisitionId, card) {
    fetch("/api/acquisitions/" + acquisitionId)
      .then(function (response) {
        return response.json();
      })
      .then(function (payload) {
        text(card, "acquisition " + payload.acquisition_id + " " + payload.status + " " + payload.reason_code);
        var sources = payload.sources || [];
        for (var index = 0; index < sources.length; index += 1) {
          var source = sources[index];
          text(card, "acquired " + source.source_id + " " + source.status + " " + source.cache_status);
          text(card, "sha256 " + source.source_sha256);
          text(card, "bytes " + source.byte_size);
          text(card, "path " + source.relative_path);
          text(card, "failure " + source.failure_code);
          if (source.probe) {
            text(card, "duration_us " + source.probe.duration_us);
            text(card, "video " + source.probe.video_codec + " " + source.probe.width + " " + source.probe.height);
            text(card, "audio " + source.probe.audio_codec + " " + source.probe.sample_rate);
          }
        }
      });
  }

  function renderSource(card, source) {
    text(card, "source " + source.source_id);
    text(card, source.display_name);
    text(card, source.notes);
    text(
      card,
      "rights " +
        source.rights_state +
        " selected " +
        source.selected +
        " verification " +
        source.verification +
        " reason " +
        source.reason_code
    );
    text(card, "sha256 " + source.source_sha256);
    text(card, "duration_us " + source.duration_us);
    text(card, "size_bytes " + source.size_bytes);
    text(card, "language " + source.language + " narration " + source.narration);
  }

  function renderEnvato(card, record) {
    text(card, "envato_provider " + record.provider + " " + record.provider_version);
    text(card, "search_tool " + record.search_tool);
    text(card, "query " + record.query);
    text(card, "item_id " + record.item_id);
    text(card, "item_url " + record.item_url);
    text(card, "duration_seconds " + record.duration_seconds);
    text(card, "direct_download_url " + record.direct_download_url);
    text(card, "rights_status " + record.rights_status);
    text(card, "license_evidence_status " + record.license_evidence_status);
    text(card, "download_status " + record.download_status);
    text(card, "renderable " + record.renderable + " reason " + record.reason_code);
  }

  function loadRuns(campaignId, card) {
    fetch("/api/campaigns/" + campaignId + "/runs")
      .then(function (response) {
        return response.json();
      })
      .then(function (payload) {
        var runs = payload.runs || [];
        text(card, "runs " + runs.length);
        for (var index = 0; index < runs.length; index += 1) {
          loadRun(runs[index].campaign_run_id, card);
        }
      });
  }

  function loadRun(runId, card) {
    fetch("/api/campaign-runs/" + runId)
      .then(function (response) {
        return response.json();
      })
      .then(function (payload) {
        text(card, "run " + payload.campaign_run_id);
        text(card, "fingerprint " + payload.fingerprint);
        text(card, "status " + payload.status + " " + payload.reason_code);
        text(card, "readiness " + payload.readiness);
        text(card, "publishing " + payload.publishing);
        var sources = payload.sources || [];
        for (var index = 0; index < sources.length; index += 1) {
          loadSource(runId, sources[index].source_id, card);
        }
      });
  }

  function loadSource(runId, sourceId, card) {
    fetch("/api/campaign-runs/" + runId + "/source/" + sourceId)
      .then(function (response) {
        return response.json();
      })
      .then(function (source) {
        text(card, "stage_source " + source.source_id + " " + source.status + " " + source.reason_code);
        text(card, "cache " + source.cache_status);
        text(card, "sha256 " + source.source_sha256);
        text(card, "review " + source.review_decision);
        text(card, "hero_review " + source.hero_review_id);
        text(card, "qa " + source.qa_status + " " + source.qa_set_id);
        text(card, "delivery " + source.delivery_relative);
        text(card, "candidate_review " + source.candidate_review_path);
        text(card, "hero_review_path " + source.hero_review_path);
        var stages = source.stages || [];
        for (var index = 0; index < stages.length; index += 1) {
          var stage = stages[index];
          text(
            card,
            "stage " +
              stage.stage +
              " " +
              stage.status +
              " cache_hit " +
              stage.cache_hit +
              " " +
              stage.reason_code
          );
        }
      });
  }

  fetch("/api/campaigns")
    .then(function (response) {
      return response.json();
    })
    .then(function (payload) {
      clear(board);
      text(board, "publishing " + payload.publishing);
      text(board, "whop_live " + payload.whop_live);
      text(board, "envato " + payload.envato);
      var names = payload.campaigns || [];
      for (var index = 0; index < names.length; index += 1) {
        fetch("/api/campaigns/" + names[index])
          .then(function (response) {
            return response.json();
          })
          .then(renderCampaign);
      }
    });
})();
