document.addEventListener("DOMContentLoaded", () => {
    const form = document.getElementById("generate-form");
    const urlInput = document.getElementById("target-url-input");
    const styleSelect = document.getElementById("video-style-select");
    const voiceSelect = document.getElementById("voice-select");
    const watermarkToggle = document.getElementById("watermark-toggle");
    const submitBtn = document.getElementById("generate-submit-btn");

    const progressPanel = document.getElementById("progress-panel");
    const progressFillBar = document.getElementById("progress-fill-bar");
    const progressPercent = document.getElementById("progress-percent");
    const progressStageTitle = document.getElementById("progress-stage-title");
    const progressJobId = document.getElementById("progress-job-id");
    const progressTimer = document.getElementById("progress-timer");
    const terminalFeed = document.getElementById("terminal-feed");

    const resultPanel = document.getElementById("video-result-panel");
    const playerVideo = document.getElementById("player-video");
    const videoSource = document.getElementById("video-source");
    const resultTitle = document.getElementById("result-video-title");
    const resultTagline = document.getElementById("result-video-tagline");
    const resultDownloadBtn = document.getElementById("result-download-btn");
    const resultResetBtn = document.getElementById("result-reset-btn");
    const scenesTimelineList = document.getElementById("scenes-timeline-list");
    const apiStatusPill = document.getElementById("api-status-pill");

    let activeJobId = null;
    let pollInterval = null;
    let timerInterval = null;
    let startTime = null;

    // Check API Health
    async function checkHealth() {
        try {
            const res = await fetch("/api/health");
            if (res.ok) {
                apiStatusPill.querySelector(".status-text").textContent = "Engine Online · v1.0";
            }
        } catch (e) {
            apiStatusPill.querySelector(".status-text").textContent = "Local Standalone";
        }
    }
    checkHealth();

    // Preset button clicks
    document.querySelectorAll(".preset-btn").forEach(btn => {
        btn.addEventListener("click", () => {
            urlInput.value = btn.dataset.url;
            urlInput.focus();
        });
    });

    // Form submission
    form.addEventListener("submit", async (e) => {
        e.preventDefault();
        const rawUrl = urlInput.value.trim();
        if (!rawUrl) return;

        // Transition UI to Progress state
        form.style.display = "none";
        progressPanel.style.display = "block";
        resultPanel.style.display = "none";
        
        terminalFeed.innerHTML = "";
        addTerminalLog(`[INIT] Target URL submitted: ${rawUrl}`);
        addTerminalLog("[SPAWN] Requesting background worker container...");

        startTime = Date.now();
        timerInterval = setInterval(updateTimer, 1000);

        try {
            const payload = {
                url: rawUrl,
                style: styleSelect.value,
                voice: voiceSelect.value,
                include_watermark: watermarkToggle.checked
            };

            const response = await fetch("/api/generate", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(payload)
            });

            if (!response.ok) {
                throw new Error(`API error: ${response.statusText}`);
            }

            const data = await response.json();
            activeJobId = data.job_id;
            progressJobId.textContent = `Job ID: ${activeJobId}`;
            addTerminalLog(`[JOB] Assigned identifier: ${activeJobId}`);

            // Start polling status
            pollInterval = setInterval(pollStatus, 1500);

        } catch (err) {
            clearInterval(timerInterval);
            addTerminalLog(`[ERROR] ${err.message}`);
            progressStageTitle.textContent = "Pipeline Failed";
            progressStageTitle.style.color = "var(--accent-rose)";
        }
    });

    function updateTimer() {
        if (!startTime) return;
        const elapsedSec = Math.floor((Date.now() - startTime) / 1000);
        const mins = String(Math.floor(elapsedSec / 60)).padStart(2, "0");
        const secs = String(elapsedSec % 60).padStart(2, "0");
        progressTimer.textContent = `${mins}:${secs}`;
    }

    function addTerminalLog(msg) {
        const line = document.createElement("div");
        line.className = "terminal-line";
        const timeStr = new Date().toLocaleTimeString();
        line.textContent = `[${timeStr}] ${msg}`;
        terminalFeed.appendChild(line);
        terminalFeed.scrollTop = terminalFeed.scrollHeight;
    }

    async function pollStatus() {
        if (!activeJobId) return;

        try {
            const res = await fetch(`/api/status/${activeJobId}`);
            if (!res.ok) return;

            const job = await res.json();
            const pct = job.progress_percent || 0;
            
            progressPercent.textContent = `${pct}%`;
            progressFillBar.style.width = `${pct}%`;
            progressStageTitle.textContent = job.current_stage || "Processing...";

            // Update step indicators
            updateStepper(pct);

            if (job.current_stage) {
                addTerminalLog(`[PROGRESS] ${pct}% — ${job.current_stage}`);
            }

            if (job.status === "completed") {
                clearInterval(pollInterval);
                clearInterval(timerInterval);
                onJobCompleted(job);
            } else if (job.status === "failed") {
                clearInterval(pollInterval);
                clearInterval(timerInterval);
                addTerminalLog(`[FATAL] ${job.error || 'Job execution failed.'}`);
                progressStageTitle.textContent = "Generation Failed";
                progressStageTitle.style.color = "var(--accent-rose)";
            }

        } catch (e) {
            console.error("Poll error:", e);
        }
    }

    function updateStepper(pct) {
        const stepBrowser = document.getElementById("step-browser");
        const stepVision = document.getElementById("step-vision");
        const stepScript = document.getElementById("step-script");
        const stepAudio = document.getElementById("step-audio");
        const stepRender = document.getElementById("step-render");

        if (pct >= 5) stepBrowser.classList.add("active");
        if (pct >= 40) stepVision.classList.add("active");
        if (pct >= 60) stepScript.classList.add("active");
        if (pct >= 75) stepAudio.classList.add("active");
        if (pct >= 85) stepRender.classList.add("active");
    }

    function onJobCompleted(job) {
        progressPanel.style.display = "none";
        resultPanel.style.display = "block";

        const brand = job.brand || {};
        resultTitle.textContent = `${brand.company_name || 'Website'} Product Video`;
        resultTagline.textContent = brand.tagline || brand.clean_domain || '';

        // Configure Video Player
        const videoUrl = job.video_url || `/api/download/${job.job_id}`;
        videoSource.src = videoUrl;
        playerVideo.load();

        resultDownloadBtn.href = job.download_url || `/api/download/${job.job_id}?attachment=true`;

        // Render scenes timeline transcript
        scenesTimelineList.innerHTML = "";
        const scenes = job.scenes || [];
        
        let currentTimeOffset = 0;
        scenes.forEach((s, idx) => {
            const card = document.createElement("div");
            card.className = "scene-item-card";

            const mins = String(Math.floor(currentTimeOffset / 60)).padStart(2, "0");
            const secs = String(Math.floor(currentTimeOffset % 60)).padStart(2, "0");
            const timeLabel = `${mins}:${secs}`;
            const dur = s.duration_sec || 10;
            currentTimeOffset += dur;

            card.innerHTML = `
                <div class="scene-time-pill">${timeLabel}</div>
                <div class="scene-text-block">
                    <div class="scene-category-tag">${s.scene_type || 'Feature'} · ${(s.title || '').split('|')[0].trim()}</div>
                    <div class="scene-narration-quote">"${s.narration || ''}"</div>
                </div>
            `;
            scenesTimelineList.appendChild(card);
        });
    }

    // Reset button
    resultResetBtn.addEventListener("click", () => {
        resultPanel.style.display = "none";
        progressPanel.style.display = "none";
        form.style.display = "block";
        urlInput.value = "";
        urlInput.focus();
    });

    // Showcase cards instant preview
    const DEMO_REGISTRY = {
        campusweb: {
            job_id: "campusweb_agency_v2",
            video_url: "/output/campusweb_agency_v2/campusweb.co.in_intro.mp4",
            download_url: "/output/campusweb_agency_v2/campusweb.co.in_intro.mp4",
            brand: {
                company_name: "CampusWeb",
                clean_domain: "campusweb.co.in",
                tagline: "Built for Coaching. Crafted for Speed & Scale."
            },
            scenes: [
                { scene_type: "Hero", title: "CampusWeb Operating Suite", duration_sec: 17, narration: "Meet CampusWeb. The purpose-built operating suite for coaching institutes. Built from the ground up to eliminate daily busywork and deliver unmatched speed, scale, and operational control." },
                { scene_type: "Dashboard", title: "Central Operations & Tracking", duration_sec: 12, narration: "Inside the core dashboard, everything is unified. From 1-tap dynamic QR attendance to automated tracking, manage your entire operations effortlessly from a single screen." },
                { scene_type: "Features", title: "Automated WhatsApp Receipts", duration_sec: 11, narration: "Engineered for high performance. Experience automated WhatsApp receipts, instant synchronization, and workflows that keep your entire organization moving forward without friction." },
                { scene_type: "Pricing", title: "Zero Commission Guarantee", duration_sec: 13, narration: "Transparent, flexible plans backed by our zero commission guarantee. Zero paperwork, zero hidden friction. Take your operations to the next level today at campusweb.co.in." }
            ]
        },
        linear: {
            job_id: "linear_agency_v2",
            video_url: "/output/linear_agency_v2/linear.app_intro.mp4",
            download_url: "/output/linear_agency_v2/linear.app_intro.mp4",
            brand: {
                company_name: "Linear",
                clean_domain: "linear.app",
                tagline: "The product development system for teams and agents."
            },
            scenes: [
                { scene_type: "Hero", title: "Linear Product System", duration_sec: 13, narration: "Meet Linear. The purpose-built platform for teams and agents. Built from the ground up to eliminate daily busywork and deliver unmatched speed, scale, and operational control." },
                { scene_type: "Dashboard", title: "Lightning Issue Tracking", duration_sec: 11, narration: "Inside the core dashboard, everything is unified. From lightning issue tracking to automated tracking, manage your entire operations effortlessly from a single screen." },
                { scene_type: "Features", title: "Automated Cycle Planning", duration_sec: 11, narration: "Engineered for high performance. Experience automated cycle planning, instant synchronization, and workflows that keep your entire organization moving forward without friction." },
                { scene_type: "Pricing", title: "Enterprise Git Sync", duration_sec: 12, narration: "Transparent, flexible plans backed by enterprise git sync. Zero paperwork, zero hidden friction. Take your operations to the next level today at linear.app." }
            ]
        }
    };

    document.querySelectorAll(".showcase-card").forEach(card => {
        card.addEventListener("click", () => {
            const demoKey = card.dataset.demo || "campusweb";
            const demoJob = DEMO_REGISTRY[demoKey] || DEMO_REGISTRY.campusweb;

            form.style.display = "none";
            progressPanel.style.display = "none";
            onJobCompleted(demoJob);
            window.scrollTo({ top: 120, behavior: "smooth" });
            playerVideo.play().catch(() => {});
        });
    });
});
