let pageAssets = [],
  pageIndex = 0,
  imageZoom = 1,
  selectedVision = 0;
function visionPayload(c) {
  const fields = [
    "question_number",
    "question_text",
    "passage",
    "choices",
    "answer_area",
    "sources",
    "visual_elements",
    "uncertain_fields",
    "continues_to_next_page",
  ];
  return Object.fromEntries(fields.map((k) => [k, c[k]]));
}
function syncVision() {
  run.candidates = run.structured_candidates.map((c) => ({
    ...c,
    text: c.question_text,
    pages: [...new Set(c.sources.map((s) => s.page_number))],
  }));
}
async function awaitJob(job) {
  while (job.status === "queued" || job.status === "running") {
    $("job-status").textContent = `작업 ${job.status} · ${job.progress}%`;
    await new Promise((resolve) => setTimeout(resolve, 700));
    job = await api(`/processing-jobs/${job.id}`);
  }
  if (job.status !== "completed")
    throw Error(job.error || "처리에 실패했습니다.");
  $("job-status").textContent = "처리 완료 · 100%";
  return job.result;
}
async function loadImages() {
  if (!$("document").value) throw Error("PDF 문서를 선택하세요.");
  const job = await api(
    `/exams/${$("exam").value}/documents/${$("document").value}/render`,
    { method: "POST" },
  );
  const result = await awaitJob(job);
  pageAssets = result.page_assets;
  pageIndex = 0;
  showImage();
  notice(
    "원본 페이지 이미지가 준비되었습니다. 스캔 PDF도 같은 이미지 흐름을 사용합니다.",
  );
}
async function startVision() {
  notice("이미지 기반 테스트 추출을 실행하고 있습니다…");
  const job = await api(
    `/exams/${$("exam").value}/documents/${$("document").value}/extract-images`,
    { method: "POST" },
  );
  const result = await awaitJob(job);
  run = await api(`/multimodal-extractions/${result.extraction_run_id}`);
  option(
    $("history"),
    run.id,
    `${displayDate(run.created_at)} · 테스트 추출(Mock Provider)`,
  );
  $("history").value = run.id;
  selectedVision = 0;
  renderVision();
  notice(
    "테스트 추출(Mock Provider): 실제 AI 문항 분리·OCR이 아닙니다. 페이지별 후보를 원본과 대조해 직접 수정하세요.",
  );
}
function showImage() {
  const asset = pageAssets[pageIndex];
  $("page-select").replaceChildren();
  pageAssets.forEach((a, i) =>
    option($("page-select"), String(i), `${a.page_number}쪽`),
  );
  $("page-select").value = String(pageIndex);
  if (!asset) {
    $("page-image").removeAttribute("src");
    $("image-regions").replaceChildren();
    return;
  }
  $("page-image").src = asset.image_url;
  $("image-stage").style.width = `${imageZoom * 100}%`;
  $("image-info").textContent =
    `${asset.page_number}쪽 · ${asset.width_px}×${asset.height_px} · ${asset.dpi} DPI`;
  $("image-regions").replaceChildren();
  const candidate =
    run?.engine === "multimodal"
      ? run.structured_candidates[selectedVision]
      : null;
  for (const source of [
    ...(candidate?.sources || []),
    ...(candidate?.visual_elements || []),
  ].filter((s) => s.page_number === asset.page_number)) {
    const box = document.createElement("div");
    box.className = "region-box";
    const [x0, y0, x1, y1] = source.bbox;
    Object.assign(box.style, {
      left: `${x0 * 100}%`,
      top: `${y0 * 100}%`,
      width: `${(x1 - x0) * 100}%`,
      height: `${(y1 - y0) * 100}%`,
    });
    box.title = source.type || "문항 출처";
    $("image-regions").append(box);
  }
}
function selectVision(index) {
  selectedVision = index;
  const source = run.structured_candidates[index]?.sources[0];
  const found = pageAssets.findIndex(
    (a) => a.page_number === source?.page_number,
  );
  if (found >= 0) pageIndex = found;
  showImage();
  document
    .querySelectorAll(".vision-candidate")
    .forEach((card, i) => card.classList.toggle("selected", i === index));
  const highlight = $("image-regions").firstElementChild;
  highlight?.scrollIntoView({ block: "nearest", inline: "nearest" });
}
function readVision() {
  if (!run?.structured_candidates) return;
  document.querySelectorAll(".vision-candidate").forEach((card, i) => {
    const c = run.structured_candidates[i];
    c.question_number = Number(card.querySelector(".number").value);
    c.question_text = card.querySelector(".vision-text").value;
    c.passage = card.querySelector(".vision-passage").value || null;
    c.choices = Array.from(card.querySelectorAll(".choice-row")).map((row) => ({
      label: row.querySelector(".choice-label").value,
      text: row.querySelector(".choice-text").value,
    }));
    const readRegions = (selector) =>
      Array.from(card.querySelectorAll(selector)).map((row) => ({
        page_number: Number(row.querySelector(".region-page").value),
        bbox: Array.from(row.querySelectorAll(".coordinate")).map(
          (input) => Number(input.value) / 100,
        ),
        ...(row.querySelector(".region-type")
          ? { type: row.querySelector(".region-type").value }
          : {}),
      }));
    c.sources = readRegions(".source-row");
    c.visual_elements = readRegions(".visual-row");
    c.answer_area = card.querySelector(".vision-answer").value || null;
    c.uncertain_fields = Array.from(
      card.querySelectorAll(".uncertain-checkbox:checked"),
    ).map((input) => input.dataset.field);
    c.continues_to_next_page = card.querySelector(".vision-continue").checked;
  });
  syncVision();
}
function addVisionMissing(number) {
  try {
    readVision();
    if (
      !Number.isInteger(number) ||
      number < 1 ||
      number > 999 ||
      run.structured_candidates.some((c) => c.question_number === number)
    )
      throw Error("새 문항 번호를 확인하세요.");
    const source = run.structured_candidates[selectedVision]?.sources || [
      { page_number: pageAssets[pageIndex].page_number, bbox: [0, 0, 1, 1] },
    ];
    const c = {
      question_number: number,
      question_text: "",
      passage: null,
      choices: [],
      answer_area: null,
      sources: structuredClone(source),
      visual_elements: [],
      uncertain_fields: ["question_text", "sources"],
      continues_to_next_page: false,
    };
    run.structured_candidates.push(c);
    run.structured_candidates.sort(
      (a, b) => a.question_number - b.question_number,
    );
    selectedVision = run.structured_candidates.indexOf(c);
    renderVision();
    selectVision(selectedVision);
    notice("빈 문항을 추가했습니다. 실제 원문과 출처 영역을 입력하세요.");
  } catch (e) {
    notice(e.message, true);
  }
}
function field(card, label, value, cls) {
  const wrap = document.createElement("label");
  wrap.textContent = label;
  const input = document.createElement("textarea");
  input.className = cls;
  input.value = value;
  wrap.append(input);
  card.append(wrap);
  return input;
}
function renderVision() {
  syncVision();
  pageAssets = run.page_assets;
  for (const id of ["candidates", "warnings", "pages"]) $(id).replaceChildren();
  $("run-info").textContent =
    `테스트 추출(Mock Provider) · ${run.status === "saved" ? "문항 저장 완료" : "검토 필요"} · ${run.structured_candidates.length}개`;
  const banner = document.createElement("p");
  banner.className = "warning";
  banner.textContent =
    "테스트 추출(Mock Provider) — 실제 AI·OCR 결과가 아닙니다. 페이지 전체를 임시 후보로 제공합니다.";
  $("warnings").append(banner);
  const missing = gaps();
  $("gap-ack-label").hidden = !missing.length || run.status === "saved";
  $("gap-ack").checked = false;
  $("add-number").value =
    missing[0] || Math.max(...run.candidates.map((c) => c.question_number)) + 1;
  const shown = new Set();
  run.structured_candidates.forEach((c, i) => {
    missing
      .filter((n) => n < c.question_number && !shown.has(n))
      .forEach((n) => {
        shown.add(n);
        const gap = document.createElement("div");
        gap.className = "gap-marker";
        gap.textContent = `${n}번 누락 가능 `;
        const b = document.createElement("button");
        b.textContent = `${n}번 누락 문항 추가`;
        b.onclick = () => addVisionMissing(n);
        gap.append(b);
        $("candidates").append(gap);
      });
    const card = document.createElement("article");
    card.className = "candidate vision-candidate";
    const label = document.createElement("label");
    label.textContent = "문항 번호";
    const num = document.createElement("input");
    num.type = "number";
    num.className = "number";
    num.min = "1";
    num.value = c.question_number;
    label.append(num);
    card.append(label);
    const jump = document.createElement("button");
    jump.textContent = "원본 영역 보기";
    jump.className = "secondary";
    jump.onclick = () => selectVision(i);
    card.append(jump);
    const text = field(card, "문항 원문", c.question_text, "vision-text");
    text.setAttribute("aria-label", `${c.question_number}번 문항 내용`);
    field(card, "지문", c.passage || "", "vision-passage");
    choiceEditor(card, c, i);
    field(card, "답안 영역", c.answer_area || "", "vision-answer");
    regionEditor(card, c, i, "sources", "출처 페이지·영역", false);
    regionEditor(card, c, i, "visual_elements", "관련 이미지·표", true);
    const uncertain = document.createElement("fieldset"),
      legend = document.createElement("legend");
    legend.textContent = "검토가 필요한 항목";
    uncertain.append(legend);
    const labels = {
      question_number: "문항 번호",
      question_text: "문항 원문",
      passage: "지문",
      choices: "선택지",
      answer_area: "답안 영역",
      sources: "출처 영역",
      visual_elements: "이미지·표",
    };
    Object.entries(labels).forEach(([field, label]) => {
      const wrap = document.createElement("label"),
        input = document.createElement("input");
      input.type = "checkbox";
      input.className = "uncertain-checkbox";
      input.dataset.field = field;
      input.checked = c.uncertain_fields.includes(field);
      wrap.append(input, document.createTextNode(label));
      uncertain.append(wrap);
    });
    card.append(uncertain);
    const cont = document.createElement("label");
    cont.textContent = "다음 페이지로 이어짐";
    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.className = "vision-continue";
    cb.checked = c.continues_to_next_page;
    cont.prepend(cb);
    card.append(cont);
    const update = document.createElement("button");
    update.textContent = "영역 표시 갱신";
    update.onclick = () => {
      try {
        readVision();
        selectVision(i);
      } catch (e) {
        notice(e.message, true);
      }
    };
    card.append(update);
    const merge = document.createElement("button");
    merge.textContent = "다음 문항과 합치기";
    merge.className = "secondary";
    merge.onclick = () => {
      try {
        readVision();
        const next = run.structured_candidates[i + 1];
        if (!next) return;
        c.question_text += "\n" + next.question_text;
        c.passage =
          [c.passage, next.passage].filter(Boolean).join("\n") || null;
        c.choices.push(...next.choices);
        c.sources.push(...next.sources);
        c.visual_elements.push(...next.visual_elements);
        c.uncertain_fields = [
          ...new Set([...c.uncertain_fields, ...next.uncertain_fields]),
        ];
        c.continues_to_next_page = next.continues_to_next_page;
        run.structured_candidates.splice(i + 1, 1);
        selectedVision = i;
        renderVision();
      } catch (e) {
        notice(e.message, true);
      }
    };
    const split = document.createElement("button");
    split.textContent = "커서 위치에서 분리";
    split.className = "secondary";
    split.onclick = () => {
      try {
        const pos = text.selectionStart;
        readVision();
        const a = c.question_text.slice(0, pos).trim(),
          b = c.question_text.slice(pos).trim();
        if (!a || !b) throw Error("본문 중간에 커서를 놓으세요.");
        const n =
          gaps().find((n) => n > c.question_number) ||
          Math.max(...run.candidates.map((q) => q.question_number)) + 1;
        c.question_text = a;
        run.structured_candidates.splice(i + 1, 0, {
          ...structuredClone(visionPayload(c)),
          question_number: n,
          question_text: b,
        });
        renderVision();
        notice("분리 후 지문·선택지·출처 영역의 중복과 번호를 확인하세요.");
      } catch (e) {
        notice(e.message, true);
      }
    };
    card.append(merge, split);
    card.addEventListener("click", () => {
      if (selectedVision !== i) selectVision(i);
    });
    if (run.status === "saved")
      card.querySelectorAll("input,textarea,button").forEach((e) => {
        if (e !== jump) e.disabled = true;
      });
    $("candidates").append(card);
  });
  controls();
  if (run.status === "saved")
    document
      .querySelectorAll(
        ".vision-candidate input,.vision-candidate textarea,.vision-candidate button",
      )
      .forEach((e) => {
        if (e.textContent !== "원본 영역 보기") e.disabled = true;
      });
  showImage();
  selectVision(Math.min(selectedVision, run.structured_candidates.length - 1));
}
async function draftVision() {
  readVision();
  run = await api(
    `/multimodal-extractions/${run.id}`,
    json("PUT", {
      expected_revision: run.revision,
      output: { questions: run.structured_candidates.map(visionPayload) },
    }),
  );
  renderVision();
}
async function saveVision() {
  const ack = $("gap-ack").checked;
  readVision();
  if (gaps().length && !ack)
    throw Error("번호 누락을 보정하거나 확인 항목을 체크하세요.");
  await draftVision();
  const result = await api(
    `/multimodal-extractions/${run.id}/save`,
    json("POST", { expected_revision: run.revision, acknowledge_missing: ack }),
  );
  run = result.run;
  renderVision();
  await questions();
  notice(
    `${result.question_ids.length}개 문항을 저장했습니다. Mock은 실제 AI 분석이 아닙니다.`,
  );
}
$("render-pages").onclick = () => task(loadImages);
$("page-prev").onclick = () => {
  pageIndex = Math.max(0, pageIndex - 1);
  showImage();
};
$("page-next").onclick = () => {
  pageIndex = Math.min(pageAssets.length - 1, pageIndex + 1);
  showImage();
};
$("page-select").onchange = () => {
  pageIndex = Number($("page-select").value);
  showImage();
};
$("zoom-in").onclick = () => {
  imageZoom = Math.min(4, imageZoom + 0.25);
  showImage();
};
$("zoom-out").onclick = () => {
  imageZoom = Math.max(0.5, imageZoom - 0.25);
  showImage();
};

function resetViewer() {
  pageAssets = [];
  pageIndex = 0;
  selectedVision = 0;
  imageZoom = 1;
  showImage();
}

function choiceEditor(card, c, index) {
  const group = document.createElement("fieldset"),
    legend = document.createElement("legend");
  legend.textContent = "선택지";
  group.append(legend);
  c.choices.forEach((choice, i) => {
    const row = document.createElement("div");
    row.className = "choice-row";
    const label = document.createElement("input");
    label.className = "choice-label";
    label.value = choice.label;
    label.setAttribute("aria-label", "선택지 번호");
    const text = document.createElement("textarea");
    text.className = "choice-text";
    text.value = choice.text;
    text.setAttribute("aria-label", "선택지 내용");
    const remove = document.createElement("button");
    remove.textContent = "선택지 삭제";
    remove.onclick = () => {
      readVision();
      c.choices.splice(i, 1);
      renderVision();
    };
    row.append(label, text, remove);
    group.append(row);
  });
  const add = document.createElement("button");
  add.textContent = "선택지 추가";
  add.onclick = () => {
    readVision();
    c.choices.push({ label: String(c.choices.length + 1), text: "" });
    renderVision();
  };
  group.append(add);
  card.append(group);
}
function regionEditor(card, c, index, key, title, visual) {
  const group = document.createElement("fieldset"),
    legend = document.createElement("legend");
  legend.textContent = title;
  group.append(legend);
  c[key].forEach((source, i) => {
    const row = document.createElement("div");
    row.className = visual ? "visual-row" : "source-row";
    const page = document.createElement("select");
    page.className = "region-page";
    pageAssets.forEach((a) =>
      option(page, String(a.page_number), `${a.page_number}쪽`),
    );
    page.value = String(source.page_number);
    row.append(page);
    if (visual) {
      const type = document.createElement("select");
      type.className = "region-type";
      option(type, "image", "이미지");
      option(type, "table", "표");
      type.value = source.type;
      row.append(type);
    }
    const coordinates = document.createElement("div");
    coordinates.className = "coordinate-fields";
    ["왼쪽 %", "위쪽 %", "오른쪽 %", "아래쪽 %"].forEach((name, n) => {
      const label = document.createElement("label");
      label.textContent = name;
      const input = document.createElement("input");
      input.type = "number";
      input.min = "0";
      input.max = "100";
      input.step = "0.1";
      input.className = "coordinate";
      input.value = source.bbox[n] * 100;
      label.append(input);
      coordinates.append(label);
    });
    row.append(coordinates);
    const remove = document.createElement("button");
    remove.textContent = "영역 삭제";
    remove.onclick = () => {
      readVision();
      c[key].splice(i, 1);
      renderVision();
    };
    row.append(remove);
    group.append(row);
  });
  const add = document.createElement("button");
  add.textContent = visual ? "이미지·표 추가" : "출처 영역 추가";
  add.onclick = () => {
    readVision();
    c[key].push({
      page_number: pageAssets[pageIndex].page_number,
      bbox: [0, 0, 1, 1],
      ...(visual ? { type: "image" } : {}),
    });
    renderVision();
  };
  group.append(add);
  card.append(group);
}
let regionDrag = null;
$("page-image").draggable = false;
$("image-stage").onpointerdown = (e) => {
  if (!run || run.engine !== "multimodal" || run.status === "saved" || busy)
    return;
  regionDrag = { x: e.clientX, y: e.clientY, page: pageIndex };
  $("image-stage").setPointerCapture(e.pointerId);
  e.preventDefault();
};
$("image-stage").onpointerup = (e) => {
  if (!regionDrag) return;
  const start = regionDrag;
  regionDrag = null;
  const rect = $("page-image").getBoundingClientRect();
  const clamp = (n) => Math.max(0, Math.min(1, n));
  const x0 = clamp((Math.min(start.x, e.clientX) - rect.left) / rect.width),
    x1 = clamp((Math.max(start.x, e.clientX) - rect.left) / rect.width),
    y0 = clamp((Math.min(start.y, e.clientY) - rect.top) / rect.height),
    y1 = clamp((Math.max(start.y, e.clientY) - rect.top) / rect.height);
  if (x1 - x0 < 0.01 || y1 - y0 < 0.01) return;
  try {
    readVision();
    const c = run.structured_candidates[selectedVision],
      page = pageAssets[start.page].page_number;
    const source = c.sources.find((s) => s.page_number === page);
    if (source) source.bbox = [x0, y0, x1, y1];
    else c.sources.push({ page_number: page, bbox: [x0, y0, x1, y1] });
    renderVision();
    pageIndex = start.page;
    showImage();
    notice("드래그한 영역으로 출처를 수정했습니다. 초안 저장으로 반영하세요.");
  } catch (error) {
    notice(error.message, true);
  }
};

$("extraction-mode").onchange = () => {
  $("extract").textContent =
    $("extraction-mode").value === "multimodal"
      ? "이미지 기반 테스트 추출"
      : "텍스트 추출 · 문항 분리";
};
