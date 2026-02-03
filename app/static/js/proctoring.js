let warningCount = 0;
const MAX_WARNINGS = 3;

function sendViolation(type) {
    fetch("/mcq/proctoring/violation", {
        method: "POST",
        headers: {
            "Content-Type": "application/json"
        },
        body: JSON.stringify({
            violation_type: type
        })
    });
}

function issueWarning(type) {
    warningCount += 1;
    alert(`Warning ${warningCount}/${MAX_WARNINGS}: ${type}`);

    sendViolation(type);

    if (warningCount >= MAX_WARNINGS) {
        alert("Maximum warnings exceeded. Test will be submitted.");
        window.location.href = "/mcq/submit";
    }
}

/* ---------- Event Listeners ---------- */

document.addEventListener("visibilitychange", function () {
    if (document.hidden) {
        issueWarning("Tab switch / Visibility change");
    }
});

window.addEventListener("blur", function () {
    issueWarning("Window focus lost");
});

document.addEventListener("copy", function (e) {
    e.preventDefault();
    issueWarning("Copy attempt blocked");
});

document.addEventListener("paste", function (e) {
    e.preventDefault();
    issueWarning("Paste attempt blocked");
});

document.addEventListener("contextmenu", function (e) {
    e.preventDefault();
    issueWarning("Right click disabled");
});
