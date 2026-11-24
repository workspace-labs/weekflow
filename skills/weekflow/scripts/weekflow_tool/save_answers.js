(() => {
  const button = document.querySelector("#save-answers");
  button.addEventListener("click", () => {
    const week = Number(button.dataset.week);
    const answers = Object.fromEntries(
      Array.from(document.querySelectorAll(".answers input:checked"), (choice) => [
        choice.closest("fieldset").dataset.changeId,
        choice.value,
      ])
    );
    const saved = { week, fingerprint: button.dataset.fingerprint, answers };
    const url = URL.createObjectURL(new Blob(
      [JSON.stringify(saved, null, 2) + "\n"], { type: "application/json" }
    ));
    const download = document.createElement("a");
    download.href = url;
    download.download = `week-${week}-answers.json`;
    document.body.append(download);
    download.click();
    download.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  });
  button.hidden = false;
})();
