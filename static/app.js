document.addEventListener("DOMContentLoaded", async function () {
  const reasoning = document.getElementById("match-reasoning-text");
  if (!reasoning) return;

  const saveBtn = document.querySelector(".save-job-btn");
  if (!saveBtn) return;
  const jobId = saveBtn.dataset.jobId;

  try {
      const response = await fetch(`/job/${jobId}/match_reasoning`);
      const data = await response.json();

      if (response.ok && data.reasoning) {
          reasoning.textContent = data.reasoning;
      } else {
          reasoning.textContent = "Could not generate reasoning.";
      }
  } catch (error) {
      reasoning.textContent = "Could not generate reasoning.";
  }
});

setTimeout(() => {
    document.querySelectorAll('.flash').forEach(f => f.remove());
  }, 2000);

  document.addEventListener("DOMContentLoaded", function () {
    const saveBtn = document.querySelector(".save-job-btn");
    if (!saveBtn) return;


    saveBtn.addEventListener("click", async function () {
        if (this.dataset.loading === "true") return;
        this.dataset.loading = "true";
        this.disabled = true;

        const jobId = this.dataset.jobId;

        try {
            const response = await fetch(`/save_job/${jobId}`, {
                method: "POST",
                headers: {"Content-Type": "application/json"}
            });

            const data = await response.json();

            if (data.status === "saved") {
                this.textContent = "Unsave Job";
            } else if (data.status === "unsaved") {
                this.textContent = "Save Job";
            } else if (data.error) {
                alert(data.error);
            }
        } catch (error) {
            console.error("Save job error:", error);
            alert("Something went wrong.");
        } finally {
            this.dataset.loading = "false";
            this.disabled = false;
        }
    });
});


