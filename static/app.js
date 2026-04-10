setTimeout(() => {
    document.querySelectorAll('.flash').forEach(f => f.remove());
}, 2000);

document.addEventListener("DOMContentLoaded", function () {
    const reasoning = document.getElementById("match-reasoning-text");
    if (reasoning) {
        const saveBtn = document.querySelector(".save-job-btn");
        if (saveBtn) {
            const jobId = saveBtn.dataset.jobId;
            fetch(`/job/${jobId}/match_reasoning`).then(r => r.json()).then(data => {
                    if (data.reasoning) {
                        reasoning.textContent = data.reasoning;
                    } else {
                        reasoning.textContent = "Could not generate reasoning.";
                    }
                })
                .catch(() => {
                    reasoning.textContent = "Could not generate reasoning.";
                });
        }
    }


    document.querySelectorAll(".save-job-btn").forEach(btn => {
        btn.addEventListener("click", async function () {
            if (this.dataset.loading == "true") return;
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
                    this.querySelector("img").src = "/static/favourite-fill.png";
                } else if (data.status == "unsaved") {
                    this.querySelector("img").src = "/static/favourite.png";
                }
            } catch (error) {
                console.error("Save job error:", error);
            } finally {
                this.dataset.loading = "false";
                this.disabled = false;
            }
        });
    });

    let currentSize = 100;

    document.getElementById('maximise').addEventListener('click', function () {
    
        if (currentSize < 160) {
            currentSize = currentSize + 10;
            document.body.style.fontSize = currentSize + "%";
    
            localStorage.setItem('textSize', currentSize);
        }
    });
    
    document.getElementById('minimise').addEventListener('click', function () {
        if (currentSize > 80) {
            currentSize = currentSize - 10;
            document.body.style.fontSize = currentSize + "%";

            localStorage.setItem('textSize', currentSize);
        }
    });
    

    document.getElementById('high-contrast').addEventListener('click', function() {
        document.body.classList.toggle('high-contrast');
        let isOn = document.body.classList.contains('high-contrast');
        
        localStorage.setItem('highContrast', isOn);
    });


    

    let savedSize = localStorage.getItem('textSize');
    if (savedSize) {
        currentSize = parseInt(savedSize);
        document.body.style.fontSize = currentSize + '%';
    }
    
    if (localStorage.getItem('highContrast') === 'true') {
        document.body.classList.add('high-contrast');
    }
});