(() => {
  const setActive = (buttons, selected) => {
    buttons.forEach(button => {
      const active = button === selected;
      button.classList.toggle("is-active", active);
      button.setAttribute("aria-selected", String(active));
      const mark = button.querySelector("b");
      if (mark) mark.textContent = active ? "−" : "+";
    });
  };

  const aiButtons = [...document.querySelectorAll(".ai-story-tab")];
  const aiStage = document.querySelector(".ai-story-stage");
  const aiImage = document.getElementById("ai-stage-image");
  const aiTitle = document.getElementById("ai-stage-title");
  aiButtons.forEach(button => button.addEventListener("click", () => {
    setActive(aiButtons, button);
    aiStage.classList.add("is-changing");
    aiImage.src = button.dataset.image;
    aiImage.alt = button.dataset.alt;
    aiTitle.textContent = button.dataset.stageTitle;
    requestAnimationFrame(() => aiStage.classList.remove("is-changing"));
  }));

  const productDetails = [
    ["Goals and portfolios", "Strategy stays connected to every project.", "One shared plan", "People and agents act with the same context."],
    ["Requests to resolution", "Route service work to the right expert instantly.", "Governed automation", "Agents resolve requests with clear permissions."],
    ["Client context", "Keep briefs, meetings, and delivery in one view.", "Durable relationships", "Teams and agents remember every commitment."],
    ["Product context", "Issues, pull requests, and decisions stay connected.", "Faster shipping", "Humans and agents coordinate every handoff."],
    ["Agentic workflows", "Connect enterprise knowledge to repeatable flows.", "Enterprise control", "Build, monitor, and govern every agent."],
  ];
  const productButtons = [...document.querySelectorAll(".productivity-tab")];
  const productStage = document.querySelector(".productivity-stage");
  const productImage = document.getElementById("product-image");
  const productTitle = document.getElementById("product-title");
  const productCopy = document.getElementById("product-copy");
  const sideFields = ["product-left-title", "product-left-copy", "product-right-title", "product-right-copy"];
  productButtons.forEach((button, index) => button.addEventListener("click", () => {
    setActive(productButtons, button);
    productStage.classList.add("is-changing");
    productTitle.textContent = button.dataset.title;
    productCopy.textContent = button.dataset.copy;
    productImage.src = button.dataset.image;
    productImage.alt = button.dataset.alt;
    sideFields.forEach((id, field) => { document.getElementById(id).textContent = productDetails[index][field]; });
    requestAnimationFrame(() => productStage.classList.remove("is-changing"));
  }));
})();
