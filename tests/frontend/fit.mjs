// The fit check of the design round (DESIGN.md "Review"): no page scroll, no clipped content,
// nothing outside the card, no scrolling inside a tab. Runs in the page; returns problems.

export async function fitProblems(page, maxHeight = 760) {
  return page.evaluate((limit) => {
    const problems = [];
    const root = window.card.shadowRoot;
    const card = root.querySelector("ha-card");
    const box = card.getBoundingClientRect();
    if (document.documentElement.scrollWidth > window.innerWidth) problems.push("page scrolls sideways");
    const wide = box.width >= 600;
    if (!wide && box.height > limit) problems.push(`card is ${Math.round(box.height)} px tall`);
    const pane = root.querySelector(".pane");
    if (pane && pane.scrollHeight > pane.clientHeight + 1 && !wide) problems.push(`pane scrolls: ${pane.scrollHeight} > ${pane.clientHeight}`);
    for (const el of root.querySelectorAll(".in *")) {
      const r = el.getBoundingClientRect();
      if (r.width === 0 || r.height === 0) continue;
      if (r.right > box.right + 1 || r.left < box.left - 1) problems.push(`${el.className || el.tagName} sticks out sideways`);
      if (!wide && pane && r.bottom > pane.getBoundingClientRect().bottom + 1 && pane.contains(el)) problems.push(`${el.className || el.tagName} is below the pane`);
      const style = getComputedStyle(el);
      if (/opt/.test(el.className) && el.scrollWidth > el.clientWidth + 1 && style.textOverflow !== "ellipsis") {
        problems.push(`option text clipped: ${el.textContent.trim()}`);
      }
    }
    return problems;
  }, maxHeight);
}
