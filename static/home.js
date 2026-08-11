document.getElementById('careerForm').addEventListener('submit', async (e) => {
    e.preventDefault();

    const role = document.getElementById('role').value.trim();
    const github = document.getElementById('github').value.trim();
    const resume = document.getElementById('resume').files[0];
    const formError = document.getElementById('formError');
    formError.hidden = true;

    if (!role) {
        formError.textContent = 'Please enter a target role.';
        formError.hidden = false;
        return;
    }
    if (!github) {
        formError.textContent = 'Please enter a GitHub username.';
        formError.hidden = false;
        return;
    }
    if (!resume) {
        formError.textContent = 'Please upload your resume PDF.';
        formError.hidden = false;
        return;
    }

    const formData = new FormData();
    formData.append('role', role);
    formData.append('github', github);
    formData.append('resume', resume);

    const button = document.querySelector('.primary-btn');
    button.disabled = true;
    button.textContent = 'Analyzing...';

    try {
        const response = await fetch('/analyze', { method: 'POST', body: formData });
        const data = await response.json();

        if (!response.ok || !data.success) {
            throw new Error(data.error || 'Analysis failed. Please try again.');
        }

        // Analysis is saved server-side; go view it on its own page.
        window.location.href = data.redirect;
    } catch (err) {
        console.error(err);
        formError.textContent = err.message || 'Analysis failed. Please try again.';
        formError.hidden = false;
        button.disabled = false;
        button.textContent = 'Analyze my profile';
    }
});

document.getElementById('viewHistoryBtn').addEventListener('click', async () => {
    const formError = document.getElementById('formError');
    formError.hidden = true;

    try {
        const response = await fetch('/history');
        const data = await response.json();
        if (!response.ok || !data.success) {
            throw new Error(data.error || 'Could not load history.');
        }

        const historySection = document.getElementById('historySection');
        const historyList = document.getElementById('historyList');
        historySection.hidden = false;

        if (!data.history.length) {
            historyList.innerHTML = '<p class="muted">No past analyses yet - run your first one above.</p>';
            return;
        }

        historyList.innerHTML = data.history.map(item => `
            <a class="history-item" href="/result/${item.id}">
                <div>
                    <strong>${escapeHtml(item.role)}</strong>
                    <span class="muted"> - ${new Date(item.created_at).toLocaleString()}</span>
                </div>
                <div class="history-scores">
                    <span>ATS: ${item.ats_score}</span>
                    <span>GitHub: ${item.github_score}</span>
                    <span>Readiness: ${item.placement_readiness}</span>
                </div>
            </a>`).join('');
    } catch (err) {
        console.error(err);
        formError.textContent = err.message || 'Could not load history.';
        formError.hidden = false;
    }
});

function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str == null ? '' : String(str);
    return div.innerHTML;
}
