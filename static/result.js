document.addEventListener('DOMContentLoaded', () => {
    const analysisElement = document.getElementById('analysisData');

    if (!analysisElement) {
        console.error('analysisData element was not found.');
        return;
    }

    let data;

    try {
        const raw = analysisElement.textContent.trim();
        data = JSON.parse(raw);
    } catch (error) {
        console.error('Unable to parse analysis data:', error);
        return;
    }

    // Render the analysis on the page
    renderResults(data);

    // PDF download button
    const downloadBtn = document.getElementById('downloadBtn');

    if (downloadBtn) {
        downloadBtn.addEventListener('click', async () => {
            const target = document.getElementById('pdfTarget');

            if (!target) {
                alert('PDF content could not be found.');
                return;
            }

            // Prevent multiple clicks while generating
            const originalText = downloadBtn.textContent;
            downloadBtn.textContent = 'Generating PDF...';
            downloadBtn.disabled = true;

            // Create a safe filename from the target role
            const roleName = (data.role || 'analysis')
                .replace(/[^a-z0-9]+/gi, '-')
                .replace(/^-+|-+$/g, '')
                .toLowerCase();

            const options = {
                margin: [0.45, 0.45, 0.45, 0.45],

                filename: `career-report-${roleName}.pdf`,

                image: {
                    type: 'jpeg',
                    quality: 0.98
                },

                html2canvas: {
                    scale: 2,
                    useCORS: true,
                    allowTaint: false,
                    backgroundColor: '#0f172a',
                    logging: false
                },

                jsPDF: {
                    unit: 'in',
                    format: 'a4',
                    orientation: 'portrait'
                },

                pagebreak: {
                    mode: ['css', 'legacy'],
                    avoid: [
                        '.card',
                        '.panel',
                        '.jobs-item',
                        '.step'
                    ]
                }
            };

            try {
                await html2pdf()
                    .set(options)
                    .from(target)
                    .save();

            } catch (error) {
                console.error('PDF generation failed:', error);
                alert('Unable to generate the PDF. Please try again.');

            } finally {
                downloadBtn.textContent = originalText;
                downloadBtn.disabled = false;
            }
        });
    }
});


/* =========================================================
   RENDER RESULTS
   ========================================================= */

function renderResults(data) {

    /* -----------------------------------------------------
       ATS SCORE
       ----------------------------------------------------- */

    const atsScore = document.getElementById('atsScore');

    if (atsScore) {
        atsScore.textContent = data.ats_score ?? 0;
    }

    const atsMethod = document.getElementById('atsMethod');

    if (atsMethod) {
        atsMethod.textContent = data.ats_score_method || '';
    }

    const atsNote = document.getElementById('atsNote');

    if (atsNote) {
        atsNote.textContent = data.ats_feedback || '';
    }


    /* -----------------------------------------------------
       PLACEMENT READINESS
       ----------------------------------------------------- */

    const readinessScore = document.getElementById('readinessScore');

    if (readinessScore) {
        readinessScore.textContent = data.placement_readiness ?? 0;
    }


    /* -----------------------------------------------------
       GITHUB SCORE
       ----------------------------------------------------- */

    const githubScore = document.getElementById('githubScore');

    if (githubScore) {
        githubScore.textContent = data.github_score ?? 0;
    }

    const langs = (
        data.github_top_languages &&
        data.github_top_languages.length
    )
        ? ` - ${data.github_top_languages.join(', ')}`
        : '';

    const githubNote = document.getElementById('githubNote');

    if (githubNote) {
        githubNote.textContent =
            `${data.github_public_repos || 0} public repos - ` +
            `${data.github_followers || 0} followers` +
            langs;
    }


    /* -----------------------------------------------------
       MISSING SKILLS
       ----------------------------------------------------- */

    const skillGap = document.getElementById('skillGap');

    if (skillGap) {

        if (
            data.missing_skills &&
            data.missing_skills.length
        ) {
            skillGap.innerHTML = data.missing_skills
                .map(skill =>
                    `<span class="chip danger">${escapeHtml(skill)}</span>`
                )
                .join('');

        } else {
            skillGap.innerHTML =
                '<p class="muted">No major skill gaps detected.</p>';
        }
    }


    /* -----------------------------------------------------
       GITHUB RECOMMENDATIONS
       ----------------------------------------------------- */

    const githubEval = document.getElementById('githubEval');

    if (githubEval) {

        if (
            data.github_recommendations &&
            data.github_recommendations.length
        ) {
            githubEval.innerHTML = data.github_recommendations
                .map(item =>
                    `<li>${escapeHtml(item)}</li>`
                )
                .join('');

        } else {
            githubEval.innerHTML =
                '<li>No recommendations available.</li>';
        }
    }


    /* -----------------------------------------------------
       PROJECT SUGGESTIONS
       ----------------------------------------------------- */

    const projects = document.getElementById('projects');

    if (projects) {

        if (
            data.projects &&
            data.projects.length
        ) {
            projects.innerHTML = data.projects
                .map(project =>
                    `<li>${escapeHtml(project)}</li>`
                )
                .join('');

        } else {
            projects.innerHTML =
                '<li>No project suggestions available.</li>';
        }
    }


    /* -----------------------------------------------------
       JOB RECOMMENDATIONS
       ----------------------------------------------------- */

    const jobs = document.getElementById('jobs');

    if (jobs) {

        if (
            data.jobs &&
            data.jobs.length
        ) {
            jobs.innerHTML = data.jobs
                .map(job => {

                    const meta = [
                        job.company,
                        job.location
                    ]
                        .filter(Boolean)
                        .join(' - ');

                    const title = escapeHtml(
                        job.title || 'Job opportunity'
                    );

                    const safeMeta = escapeHtml(meta);

                    let applyLink = '';

                    if (job.url) {
                        applyLink = `
                            <a
                                href="${escapeAttribute(job.url)}"
                                target="_blank"
                                rel="noopener noreferrer"
                            >
                                Apply
                            </a>
                        `;
                    }

                    return `
                        <div class="jobs-item">

                            <h4>${title}</h4>

                            ${
                                safeMeta
                                    ? `<p>${safeMeta}</p>`
                                    : ''
                            }

                            ${applyLink}

                        </div>
                    `;
                })
                .join('');

        } else {

            jobs.innerHTML =
                '<p class="muted">No jobs found right now.</p>';
        }
    }


    /* -----------------------------------------------------
       ROADMAP
       ----------------------------------------------------- */

    const roadmap = document.getElementById('roadmapTimeline');

    if (roadmap) {

        if (
            data.roadmap &&
            data.roadmap.length
        ) {

            roadmap.innerHTML = data.roadmap
                .map(step => {

                    const week = escapeHtml(
                        step.week || ''
                    );

                    const focus = step.focus
                        ? ` - ${escapeHtml(step.focus)}`
                        : '';

                    const tasks = escapeHtml(
                        step.tasks || ''
                    );

                    return `
                        <div class="step">

                            <span>
                                ${week}${focus}
                            </span>

                            <p>
                                ${tasks}
                            </p>

                        </div>
                    `;
                })
                .join('');

        } else {

            roadmap.innerHTML =
                '<p class="muted">No roadmap generated.</p>';
        }
    }
}


/* =========================================================
   HTML SECURITY HELPERS
   ========================================================= */

function escapeHtml(value) {

    const div = document.createElement('div');

    div.textContent =
        value == null
            ? ''
            : String(value);

    return div.innerHTML;
}


/*
 * Used specifically for URLs placed inside href=""
 * attributes.
 */
function escapeAttribute(value) {

    return String(value == null ? '' : value)
        .replace(/&/g, '&amp;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;');
}
