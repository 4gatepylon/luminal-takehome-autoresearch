"use strict";

const search = document.querySelector("#search");
const cards = [...document.querySelectorAll(".card")];
const count = document.querySelector("#count");
const empty = document.querySelector("#empty");

document.querySelector(".toolbar").hidden = false;
search.addEventListener("input", () => {
  const query = search.value.trim().toLowerCase();
  let visible = 0;
  for (const card of cards) {
    const title = card.querySelector(".card-heading").textContent.toLowerCase();
    card.hidden = !title.includes(query);
    if (!card.hidden) visible += 1;
  }
  count.textContent = `${visible} of ${cards.length} programs`;
  empty.hidden = visible !== 0;
});
