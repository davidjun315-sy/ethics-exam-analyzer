const $ = (id) => document.getElementById(id);
let run = null,
  busy = false;
const displayDate = (value) =>
  new Date(
    /[Zz]$|[+-]\d{2}:\d{2}$/.test(value) ? value : value + "Z",
  ).toLocaleString("ko-KR", { timeZone: "Asia/Seoul" });
const statuses = {
  extracted: "추출 완료 · 검토 필요",
  partial: "일부 페이지 OCR 필요",
  needs_ocr: "OCR 필요",
  saved: "문항 저장 완료",
};
function notice(text, error = false) {
  $("message").textContent = text;
  $("message").className = "notice" + (error ? " error" : "");
}
async function api(path, options = {}) {
  const res = await fetch(path, options);
  let data;
  try {
    data = await res.json();
  } catch {
    throw Error("서버 응답을 읽을 수 없습니다.");
  }
  if (!res.ok)
    throw Error(
      typeof data.detail === "string"
        ? data.detail
        : JSON.stringify(data.detail),
    );
  return data;
}
const json = (method, data) => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(data),
});
function controls() {
  document.querySelectorAll("button").forEach((b) => (b.disabled = busy));
  $("exam").disabled = busy;
  $("document").disabled = busy;
  $("history").disabled = busy;
  $("extract").disabled = busy || !$("document").value;
  $("render-pages").disabled = busy || !$("document").value;
  $("add-missing").disabled =
    busy || !run || run.status === "saved" || !run.original_candidates.length;
  document
    .querySelectorAll(".gap-marker button")
    .forEach((b) => (b.disabled = busy || run.status === "saved"));
  $("draft").disabled = $("save").disabled =
    busy || !run || run.status === "saved" || !run.candidates.length;
  document.querySelectorAll(".candidate button").forEach((b) => {
    b.disabled =
      busy ||
      !run ||
      run.status === "saved" ||
      (b.textContent === "다음 문항과 합치기" &&
        b.closest(".candidate") === $("candidates").lastElementChild);
  });
}
async function task(fn) {
  if (busy) return;
  busy = true;
  controls();
  try {
    await fn();
  } catch (e) {
    notice(e.message, true);
  } finally {
    busy = false;
    controls();
  }
}
function option(select, value, text) {
  const o = document.createElement("option");
  o.value = value;
  o.textContent = text;
  select.append(o);
}
async function exams(selected) {
  $("exam").replaceChildren();
  option($("exam"), "", "시험을 선택하세요");
  for (let offset = 0; ; offset += 200) {
    const rows = await api(`/exams?limit=200&offset=${offset}`);
    rows.forEach((e) => option($("exam"), e.id, `${e.exam_id} · ${e.title}`));
    if (rows.length < 200) break;
  }
  if (selected) $("exam").value = selected;
}
async function questions() {
  const id = $("exam").value;
  const box = $("questions");
  box.replaceChildren();
  if (!id) return;
  let count = 0;
  for (let offset = 0; ; offset += 200) {
    const rows = await api(
      `/questions?exam_id=${encodeURIComponent(id)}&limit=200&offset=${offset}`,
    );
    rows.forEach((q) => {
      count++;
      const d = document.createElement("details"),
        s = document.createElement("summary"),
        p = document.createElement("pre");
      s.textContent = `${q.question_number}번 · 출처 ${q.sources.map((x) => x.page_number).join(", ")}쪽`;
      p.textContent = q.question_text;
      d.append(s, p);
      box.append(d);
    });
    if (rows.length < 200) break;
  }
  if (!count) box.textContent = "아직 저장된 문항이 없습니다.";
}
async function context() {
  run = null;
  if (typeof resetViewer === "function") resetViewer();
  render();
  $("document-info").textContent = "";
  $("document").replaceChildren();
  $("history").replaceChildren();
  option($("document"), "", "문서를 선택하세요");
  option($("history"), "", "추출 결과를 선택하세요");
  const exam = $("exam").value;
  if (!exam) {
    $("questions").replaceChildren();
    return;
  }
  const docs = await api(`/exams/${exam}/uploaded-documents`);
  docs.forEach((d) =>
    option($("document"), d.id, `${d.filename} · ${d.page_count}쪽`),
  );
  const runs = await api(`/exams/${exam}/extractions`);
  runs.forEach((r) =>
    option(
      $("history"),
      r.id,
      `${displayDate(r.created_at)} · ${statuses[r.status] || r.status}`,
    ),
  );
  await questions();
}
function readEditors() {
  if (run?.engine === "multimodal") {
    readVision();
    return;
  }
  if (!run) return;
  document.querySelectorAll(".candidate").forEach((node, i) => {
    run.candidates[i].question_number = Number(
      node.querySelector(".number").value,
    );
    run.candidates[i].text = node.querySelector("textarea").value;
    run.candidates[i].pages = node
      .querySelector(".page-input")
      .value.split(",")
      .map((x) => Number(x.trim()));
  });
}
function gaps() {
  if (!run) return [];
  const nums = new Set(
    run.candidates
      .map((c) => c.question_number)
      .filter((n) => Number.isInteger(n) && n > 0 && n <= 999),
  );
  const max = Math.max(0, ...nums);
  return Array.from({ length: max }, (_, i) => i + 1).filter(
    (n) => !nums.has(n),
  );
}
function addMissing(number) {
  if (run?.engine === "multimodal") {
    addVisionMissing(number);
    return;
  }
  readEditors();
  if (!Number.isInteger(number) || number < 1 || number > 999) {
    notice("1~999 사이 문항 번호를 입력하세요.", true);
    return;
  }
  if (run.candidates.some((c) => c.question_number === number)) {
    notice("이미 존재하는 문항 번호입니다.", true);
    return;
  }
  const index = run.candidates.findIndex((c) => c.question_number > number);
  const insert = index < 0 ? run.candidates.length : index;
  const neighbors = [run.candidates[insert - 1], run.candidates[insert]].filter(
    Boolean,
  );
  const sources = [...new Set(neighbors.flatMap((c) => c.source_indexes))];
  if (!sources.length) {
    notice("원본 후보가 없습니다. OCR이 필요한 문서를 확인하세요.", true);
    return;
  }
  const pages = [
    ...new Set(sources.flatMap((i) => run.original_candidates[i].pages)),
  ].sort((a, b) => a - b);
  run.candidates.splice(insert, 0, {
    question_number: number,
    text: "",
    pages,
    source_indexes: sources,
  });
  render();
  const area = Array.from(document.querySelectorAll(".candidate"))
    .find((card) => Number(card.querySelector(".number").value) === number)
    ?.querySelector("textarea");
  area?.focus();
  notice(
    `${number}번 빈 후보를 추가했습니다. 페이지 원문 또는 이전 후보에서 해당 본문을 옮겨 넣고, 중복 내용과 출처 페이지를 확인하세요.`,
  );
}
function render() {
  if (run?.engine === "multimodal") {
    renderVision();
    return;
  }
  for (const id of ["candidates", "warnings", "pages"]) $(id).replaceChildren();
  $("run-info").textContent = run
    ? `${statuses[run.status] || run.status} · 후보 ${run.candidates.length}개 · 수정 버전 ${run.revision}`
    : "추출 결과를 선택하거나 추출을 실행하세요.";
  $("gap-ack-label").hidden = !run || !gaps().length || run.status === "saved";
  $("gap-ack").checked = false;
  if (!run) {
    $("candidates").textContent = "추출을 실행하면 문항 후보가 표시됩니다.";
    controls();
    return;
  }
  [
    ...run.warnings.filter((w) => !w.includes("번 문항 경계 누락 가능성:")),
    ...gaps().map(
      (n) =>
        `${n}번 문항 경계 누락 가능성: 원문을 확인하고 누락 문항을 추가하거나 분리하세요.`,
    ),
  ].forEach((t) => {
    const p = document.createElement("p");
    p.className = "warning";
    p.textContent = t;
    $("warnings").append(p);
  });
  const missing = gaps();
  $("add-number").value =
    missing[0] ||
    Math.max(0, ...run.candidates.map((c) => c.question_number)) + 1;
  const shown = new Set();
  run.candidates.forEach((c, i) => {
    for (const n of missing.filter(
      (n) => n < c.question_number && !shown.has(n),
    )) {
      shown.add(n);
      const gap = document.createElement("div");
      gap.className = "gap-marker";
      const text = document.createElement("strong");
      text.textContent = `${n}번 누락 가능`;
      const button = document.createElement("button");
      button.className = "secondary";
      button.textContent = `${n}번 누락 문항 추가`;
      button.onclick = () => addMissing(n);
      const diagnosis = document.createElement("p");
      diagnosis.className = "hint";
      diagnosis.textContent =
        run.boundary_report?.find((r) => r.question_number === n)?.cause ||
        "원문과 후보 내용을 확인하세요.";
      gap.append(text, button, diagnosis);
      $("candidates").append(gap);
    }
    const card = document.createElement("article");
    card.className = "candidate";
    const head = document.createElement("div");
    head.className = "candidate-head";
    const label = document.createElement("label");
    label.textContent = "문항 번호";
    const input = document.createElement("input");
    input.type = "number";
    input.min = "1";
    input.value = c.question_number;
    input.className = "number";
    label.append(input);
    const pl = document.createElement("label");
    pl.textContent = "출처 페이지 (쉼표 구분)";
    const pi = document.createElement("input");
    pi.value = c.pages.join(", ");
    pi.className = "page-input";
    pl.append(pi);
    head.append(label, pl);
    const tl = document.createElement("label");
    tl.textContent = "추출된 문항 내용";
    const area = document.createElement("textarea");
    area.value = c.text;
    area.setAttribute("aria-label", `${c.question_number}번 문항 내용`);
    tl.append(area);
    const status = document.createElement("span");
    status.className = "status";
    status.textContent = run.status === "saved" ? "저장 완료" : "검토 필요";
    card.append(head, status, tl);
    const merge = document.createElement("button");
    merge.textContent = "다음 문항과 합치기";
    merge.className = "secondary";
    merge.disabled = i === run.candidates.length - 1 || run.status === "saved";
    merge.onclick = () => {
      readEditors();
      const next = run.candidates[i + 1];
      c.text += "\n" + next.text;
      c.pages = [...new Set([...c.pages, ...next.pages])].sort((a, b) => a - b);
      c.source_indexes = [
        ...new Set([...c.source_indexes, ...next.source_indexes]),
      ];
      run.candidates.splice(i + 1, 1);
      render();
    };
    const split = document.createElement("button");
    split.textContent = "커서 위치에서 분리";
    split.className = "secondary";
    split.disabled = run.status === "saved";
    split.onclick = () => {
      const pos = area.selectionStart;
      readEditors();
      const a = c.text.slice(0, pos).trim(),
        b = c.text.slice(pos).trim();
      if (!a || !b) {
        notice("문항 내용 중간에 커서를 놓고 분리해 주세요.", true);
        return;
      }
      const next = run.candidates[i + 1]?.question_number || Infinity;
      const number =
        gaps().find((n) => n > c.question_number && n < next) ||
        Math.max(...run.candidates.map((x) => x.question_number)) + 1;
      c.text = a;
      run.candidates.splice(i + 1, 0, {
        question_number: number,
        text: b,
        pages: [...c.pages],
        source_indexes: [...c.source_indexes],
      });
      render();
      notice(
        "분리했습니다. 새 문항 번호와 출처 페이지를 확인하고 저장해 주세요.",
      );
    };
    card.append(merge, split);
    if (run.status === "saved")
      card
        .querySelectorAll("input,textarea")
        .forEach((x) => (x.disabled = true));
    $("candidates").append(card);
  });
  run.pages.forEach((p) => {
    const h = document.createElement("h3"),
      pre = document.createElement("pre");
    h.textContent = `${p.page_number}쪽 · ${statuses[p.extraction_status] || p.extraction_status}`;
    pre.textContent = p.text || "추출할 텍스트가 없습니다.";
    $("pages").append(h, pre);
    if (p.diagnostics?.lines) {
      const details = document.createElement("details"),
        summary = document.createElement("summary"),
        data = document.createElement("pre");
      summary.textContent = "번호 탐지 진단 · 좌표 · 원래 읽기 순서";
      const diag = p.diagnostics;
      const markers = diag.lines.filter(
        (l) => l.number !== null || l.kind === "choice",
      );
      data.textContent =
        `텍스트 문자 ${diag.char_count}개 / 단어 ${diag.word_count}개\n2단: ${diag.two_columns ? "감지" : "아님"} / 분리 x좌표: ${diag.gutter_x ?? "없음"}\n원래 번호 순서: ${diag.native_number_order.join(", ")}\n좌표 정렬 번호: ${diag.layout_number_order.join(", ")}\n` +
        markers
          .map(
            (l) =>
              `${l.number ?? "원형 선택지"} / x=${l.x0}, y=${l.top}, 열=${l.column} / ${l.accepted ? "채택" : "제외"}: ${l.reason} / ${l.text}`,
          )
          .join("\n");
      const native = document.createElement("pre");
      native.textContent = diag.native_text || "기본 추출 텍스트 없음";
      details.append(summary, data, native);
      $("pages").append(details);
    }
  });
  controls();
  document.querySelectorAll(".candidate button").forEach((b, i) => {
    b.disabled =
      busy ||
      run.status === "saved" ||
      (b.textContent === "다음 문항과 합치기" &&
        b.closest(".candidate") === $("candidates").lastElementChild);
  });
}
$("exam").onchange = () => task(context);
$("exam-form").onsubmit = (e) => {
  e.preventDefault();
  task(async () => {
    const exam = await api(
      "/exams",
      json("POST", {
        year: Number($("year").value),
        exam_part: $("part").value,
        title: $("title").value,
      }),
    );
    await exams(exam.id);
    await context();
    notice("시험을 생성했습니다. PDF를 업로드해 주세요.");
  });
};
$("upload-form").onsubmit = (e) => {
  e.preventDefault();
  task(async () => {
    if (!$("exam").value) throw Error("먼저 시험을 선택해 주세요.");
    const file = $("pdf").files[0];
    if (!file) throw Error("PDF 파일을 선택해 주세요.");
    const form = new FormData();
    form.append("file", file);
    const result = await api(`/exams/${$("exam").value}/upload`, {
      method: "POST",
      body: form,
    });
    await context();
    $("document").value = result.document.id;
    $("document-info").textContent =
      `${result.document.filename} · ${result.document.page_count}쪽 · SHA256 ${result.document.sha256}`;
    notice(
      result.duplicate
        ? "동일 PDF를 감지해 기존 문서를 연결했습니다."
        : "PDF 업로드가 완료되었습니다. 추출 버튼을 눌러 주세요.",
    );
  });
};
$("document").onchange = controls;
$("extract").onclick = () =>
  task(async () => {
    if ($("extraction-mode").value === "multimodal") {
      await startVision();
      return;
    }
    notice("보조 텍스트를 추출하고 문항을 분리하고 있습니다…");
    run = await api(
      `/exams/${$("exam").value}/documents/${$("document").value}/extract`,
      json("POST", {
        column_mode: $("column-mode").value,
        allow_circled: $("circled-numbers").checked,
      }),
    );
    option(
      $("history"),
      run.id,
      `${displayDate(run.created_at)} · ${statuses[run.status]}`,
    );
    $("history").value = run.id;
    render();
    notice("추출 결과를 확인하세요. 수정 후 문항으로 저장할 수 있습니다.");
  });
$("history").onchange = () =>
  task(async () => {
    run = $("history").value
      ? await api(`/extractions/${$("history").value}`)
      : null;
    render();
  });
async function draft() {
  if (run?.engine === "multimodal") {
    await draftVision();
    return;
  }
  readEditors();
  run = await api(
    `/extractions/${run.id}`,
    json("PUT", {
      expected_revision: run.revision,
      candidates: run.candidates,
    }),
  );
  render();
}
$("draft").onclick = () =>
  task(async () => {
    await draft();
    notice("수정 초안을 저장했습니다. 아직 문항 DB에는 반영되지 않았습니다.");
  });
$("save").onclick = () =>
  task(async () => {
    if (run?.engine === "multimodal") {
      await saveVision();
      return;
    }
    const acknowledged = $("gap-ack").checked;
    readEditors();
    if (gaps().length && !acknowledged)
      throw Error("누락 문항을 보정하거나 번호 누락 확인 항목을 체크하세요.");
    await draft();
    const result = await api(
      `/extractions/${run.id}/save`,
      json("POST", {
        expected_revision: run.revision,
        acknowledge_missing: acknowledged,
      }),
    );
    run = result.run;
    const selected = $("history").selectedOptions[0];
    if (selected)
      selected.textContent = `${displayDate(run.created_at)} · ${statuses[run.status]}`;
    render();
    await questions();
    notice(
      `${result.question_ids.length}개 문항을 저장했습니다. 아래 ‘저장된 문항’에서 확인하세요.`,
    );
  });
$("add-missing").onclick = () => addMissing(Number($("add-number").value));
$("refresh").onclick = () => task(questions);
task(() => exams());
