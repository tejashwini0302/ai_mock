document.addEventListener('DOMContentLoaded', () => {
    const raw = document.getElementById('analysisData').textContent;
    const data = JSON.parse(raw);
    renderResults(data);

    document.getElementById('downloadBtn').addEventListener('click', () => {
        const target = document.getElementById('pdfTarget');
        const opt = {
            margin: 0.4,
            filename: `career-report-${(data.role || 'analysis').replace(/\s+/g, '-').toLowerCase()}.pdf`,
            image: { type: 'jpeg', quality: 0.95 },
            html2canvas: { scale: 2, backgroundColor: '#0f172a' },
            jsPDF: { unit: 'in', format: 'letter', orientation: 'portrait' }
        };
        html2pdf().set(opt).from(target).save();
    });
});

function renderResults(data) {
    document.getElementById('atsScore').textContent = data.ats_score;
    document.getElementById('atsMethod').textContent = data.ats_score_method || '';
    document.getElementById('atsNote').textContent = data.ats_feedback || '';

    document.getElementById('readinessScore').textContent = data.placement_readiness;

    document.getElementById('githubScore').textContent = data.github_score;
    const langs = (data.github_top_languages && data.github_top_languages.length)
        ? ` - ${data.github_top_languages.join(', ')}`
        : '';
    document.getElementById('githubNote').textContent =
        `${data.github_public_repos || 0} public repos - ${data.github_followers || 0} followers${langs}`;

    const skillGap = document.getElementById('skillGap');
    skillGap.innerHTML = (data.missing_skills && data.missing_skills.length)
        ? data.missing_skills.map(skill => `<span class="chip danger">${escapeHtml(skill)}</span>`).join('')
        : '<p class="muted">No major skill gaps detected.</p>';

    const githubEval = document.getElementById('githubEval');
    githubEval.innerHTML = (data.github_recommendations && data.github_recommendations.length)
        ? data.github_recommendations.map(item => `<li>${escapeHtml(item)}</li>`).join('')
        : '<li>No recommendations available.</li>';

    const projects = document.getElementById('projects');
    projects.innerHTML = (data.projects && data.projects.length)
        ? data.projects.map(project => `<li>${escapeHtml(project)}</li>`).join('')
        : '<li>No project suggestions available.</li>';

    const jobs = document.getElementById('jobs');
    jobs.innerHTML = (data.jobs && data.jobs.length)
        ? data.jobs.map(job => {
            const meta = [job.company, job.location].filter(Boolean).join(' - ');
            return `
            <div class="jobs-item">
                <h4>${escapeHtml(job.title)}</h4>
                ${meta ? `<p>${escapeHtml(meta)}</p>` : ''}
                ${job.url ? `<a href="${job.url}" target="_blank" rel="noopener">Apply</a>` : ''}
            </div>`;
          }).join('')
        : '<p class="muted">No jobs found right now.</p>';

    const roadmap = document.getElementById('roadmapTimeline');
    roadmap.innerHTML = (data.roadmap && data.roadmap.length)
        ? data.roadmap.map(step => `
            <div class="step">
                <span>${escapeHtml(step.week)}${step.focus ? ' - ' + escapeHtml(step.focus) : ''}</span>
                <p>${escapeHtml(step.tasks)}</p>
            </div>`).join('')
        : '<p class="muted">No roadmap generated.</p>';
}

function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str == null ? '' : String(str);
    return div.innerHTML;
}
