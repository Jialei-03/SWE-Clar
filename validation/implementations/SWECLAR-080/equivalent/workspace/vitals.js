(function () {
    const limits = { LCP: 2500, INP: 200, CLS: 0.1 };

    window.directoryMeasurements = {};
    window.directoryReadiness = function (values) {
        const observed = values && typeof values === 'object' ? values : {};
        const failed = [];
        const missing = [];

        for (const [name, limit] of Object.entries(limits)) {
            const value = observed[name];
            if (typeof value !== 'number' || !Number.isFinite(value) || value < 0) {
                missing.push(name);
            } else if (value > limit) {
                failed.push(name);
            }
        }

        return {
            ready: failed.length === 0 && missing.length === 0,
            failed,
            missing,
        };
    };

    function renderMeasurementStatus() {
        const status = document.querySelector('#vitals-status');
        if (!status) {
            return;
        }

        const result = window.directoryReadiness(window.directoryMeasurements);
        if (result.missing.length) {
            status.textContent = 'Still waiting for: ' + result.missing.join(', ');
        } else if (result.failed.length) {
            status.textContent = 'Lab thresholds exceeded: ' + result.failed.join(', ');
        } else {
            status.textContent = 'Observed lab values meet the example thresholds.';
        }
    }

    function observed(metric) {
        if (!metric || typeof metric.name !== 'string') {
            return;
        }

        // Keep the actual library value, including an invalid one.  The
        // readiness policy classifies invalid, negative and nonfinite values
        // as missing instead of inventing a zero observation.
        window.directoryMeasurements[metric.name] = metric.value;
        renderMeasurementStatus();
    }

    if (window.webVitals) {
        window.webVitals.onLCP(observed, { reportAllChanges: true });
        window.webVitals.onINP(observed, { reportAllChanges: true });
        window.webVitals.onCLS(observed, { reportAllChanges: true });
    }
}());
