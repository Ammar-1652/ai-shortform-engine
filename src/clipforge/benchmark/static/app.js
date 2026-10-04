(function () {
  function line(parent, value) {
    var row = document.createElement("p");
    row.textContent = value;
    parent.appendChild(row);
  }

  fetch("api/benchmark")
    .then(function (response) {
      return response.json();
    })
    .then(function (payload) {
      var run = payload.run;
      var readiness = payload.readiness;
      document.getElementById("status").textContent =
        "benchmark " + run.benchmark_run_id + " overall " + readiness.overall;
      var stages = document.getElementById("stages");
      var items = run.stages || [];
      for (var index = 0; index < items.length; index += 1) {
        line(stages, items[index].stage + " " + items[index].status);
      }
      var notes = document.getElementById("narration");
      var narration = payload.narration || [];
      if (!narration.length) {
        line(notes, "narration evidence none");
      }
      for (var narrationIndex = 0; narrationIndex < narration.length; narrationIndex += 1) {
        line(notes, narration[narrationIndex]);
      }
      var manual = run.manual_actions || [];
      if (!manual.length) {
        line(notes, "narration evidence none");
      }
      for (var noteIndex = 0; noteIndex < manual.length; noteIndex += 1) {
        line(notes, manual[noteIndex]);
      }
      if (run.warnings) {
        for (var warningIndex = 0; warningIndex < run.warnings.length; warningIndex += 1) {
          line(notes, run.warnings[warningIndex]);
        }
      }
    })
    .catch(function () {
      document.getElementById("status").textContent = "Benchmark evidence could not be loaded.";
    });
})();
