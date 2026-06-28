#!/usr/bin/env node

import fs from "node:fs";
import path from "node:path";
import process from "node:process";
import { chromium } from "playwright";

const ROOT = path.resolve(import.meta.dirname, "../..");
const CONFIG_PATH = path.join(import.meta.dirname, "config.json");
const RESULTS_PATH = path.join(
  ROOT,
  "exports/publication-input/course/results.json",
);
const SECTION_CODE = process.env.SECTION_CODE || "COURSE101-001V";
const STUDENTS_PATH = path.join(ROOT, "evaluations", SECTION_CODE, "students.json");
const SESSION_PATH = path.join(import.meta.dirname, ".ava-session");
const REPORTS_PATH = path.join(import.meta.dirname, "reports");

function fail(message) {
  throw new Error(message);
}

function normalizeText(value) {
  return String(value ?? "")
    .normalize("NFD")
    .replace(/\p{Diacritic}/gu, "")
    .replace(/\s+/g, " ")
    .trim()
    .toUpperCase();
}

function normalizeRut(value) {
  return String(value ?? "").replace(/[^0-9kK]/g, "").toUpperCase();
}

function gradingPanel(page) {
  return page
    .locator(
      ".bb-offcanvas-panel.flexible-attempt-grading-panel[aria-hidden='false']",
    )
    .last();
}

function parseArgs(argv) {
  const args = {
    all: false,
    commit: false,
    headless: false,
    inspect: false,
    feedbackOnly: false,
    evaluationId: null,
    conversionPolicy: null,
    studentRut: null,
    directUrl: null,
  };

  for (let index = 0; index < argv.length; index += 1) {
    const value = argv[index];
    if (value === "--all") args.all = true;
    else if (value === "--commit") args.commit = true;
    else if (value === "--headless") args.headless = true;
    else if (value === "--inspect") args.inspect = true;
    else if (value === "--feedback-only") args.feedbackOnly = true;
    else if (value === "--evaluation") args.evaluationId = argv[++index];
    else if (value === "--conversion") args.conversionPolicy = argv[++index];
    else if (value === "--student") args.studentRut = normalizeRut(argv[++index]);
    else if (value === "--url") args.directUrl = argv[++index];
    else if (value === "--help") {
      console.log(`Uso:
  node ava-import.mjs --inspect
  node ava-import.mjs --student RUT
  node ava-import.mjs --commit --student RUT [--conversion exact|floor|nearest]
  node ava-import.mjs --commit --student RUT --feedback-only
  node ava-import.mjs --commit --all [--conversion exact|floor|nearest]

Sin --commit solo inspecciona y compara. El guardado exige --student o --all.`);
      process.exit(0);
    } else {
      fail(`argumento desconocido: ${value}`);
    }
  }

  if (args.all && args.studentRut) fail("usa --all o --student, no ambos");
  if (
    args.conversionPolicy &&
    !["exact", "floor", "nearest"].includes(args.conversionPolicy)
  ) {
    fail("--conversion debe ser exact, floor o nearest");
  }
  if (args.commit && !args.all && !args.studentRut) {
    fail("--commit exige --student RUT o --all");
  }
  return args;
}

function readJson(filePath, label) {
  if (!fs.existsSync(filePath)) fail(`falta ${label}: ${filePath}`);
  try {
    return JSON.parse(fs.readFileSync(filePath, "utf8"));
  } catch (error) {
    fail(`${label} no es JSON válido: ${error.message}`);
  }
}

function validateConfig(config) {
  if (!config.gradebookUrl || config.gradebookUrl.includes("REEMPLAZAR")) {
    fail("define gradebookUrl en automation/ava/config.json");
  }
  if (!config.evaluationId) fail("falta evaluationId en config.json");
  if (!Array.isArray(config.rubricLevels) || config.rubricLevels.length === 0) {
    fail("falta rubricLevels en config.json");
  }
}

function loadStudents() {
  const payload = readJson(STUDENTS_PATH, "roster del curso");
  const students = new Map();
  for (const student of payload.students) {
    const rut = normalizeRut(student.rut);
    students.set(rut, {
      ...student,
      avaName: `${student.lastName} ${student.secondLastName}, ${student.names}`,
    });
  }
  return students;
}

function loadResults(evaluationId, selectedRut) {
  const students = loadStudents();
  const payload = readJson(RESULTS_PATH, "export de resultados");
  const results = [];

  for (const item of payload.items) {
    const rut = normalizeRut(item.studentId);
    if (item.evaluationId !== evaluationId || item.status !== "Evaluada") continue;
    if (selectedRut && rut !== selectedRut) continue;
    if (!Array.isArray(item.ies) || item.ies.length === 0) {
      fail(`${rut}: no contiene resultados por IE`);
    }
    const student = students.get(rut);
    if (!student) fail(`${rut}: no existe en evaluations/${SECTION_CODE}/students.json`);
    results.push({ ...item, rut, student });
  }

  if (selectedRut && results.length === 0) {
    fail(`no hay resultado evaluado para ${selectedRut} en ${evaluationId}`);
  }
  if (results.length === 0) fail(`no hay resultados evaluados para ${evaluationId}`);
  return results;
}

async function addSessionCookie(context, config) {
  const jsessionid = process.env.AVA_JSESSIONID;
  if (!jsessionid) return;
  await context.addCookies([
    {
      name: "JSESSIONID",
      value: jsessionid,
      domain: config.cookieDomain || "campusvirtual.duoc.cl",
      path: "/",
      httpOnly: true,
      secure: true,
      sameSite: "Lax",
    },
  ]);
}

async function waitForAva(page, config) {
  await gradingPanel(page).waitFor({ state: "visible" });
  await page.waitForTimeout(config.navigationDelayMs);
}

async function expandStudentNavigation(page, config) {
  const toggle = gradingPanel(page)
    .getByRole("button", { name: "Panel de navegación", exact: true })
    .first();
  await toggle.waitFor({ state: "visible" });
  if ((await toggle.getAttribute("aria-expanded")) !== "true") {
    await toggle.click();
    await page.waitForFunction(
      () => {
        const buttons = [...document.querySelectorAll("button")];
        return buttons.some(
          (button) =>
            button.getAttribute("aria-label") === "Panel de navegación" &&
            button.getAttribute("aria-expanded") === "true" &&
            button.getAttribute("aria-hidden") !== "true",
        );
      },
      undefined,
      { timeout: config.timeoutMs },
    );
    await page.waitForTimeout(config.navigationDelayMs);
  }
}

async function inspectPage(page, config) {
  const firstCriterion = gradingPanel(page)
    .locator("button[aria-expanded='false']")
    .filter({ hasText: "Inicializa las variables" })
    .first();
  if (await firstCriterion.isVisible().catch(() => false)) {
    await firstCriterion.click();
    await page.waitForTimeout(500);
  }
  const firstCriterionComment = gradingPanel(page)
    .getByRole("button", { name: /^Agregar comentarios al criterio:/ })
    .first();
  if (await firstCriterionComment.isVisible().catch(() => false)) {
    await firstCriterionComment.click();
    await page.waitForTimeout(500);
  }
  const visibleText = await page.locator("body").innerText();
  const lines = visibleText
    .split("\n")
    .map((line) => line.trim())
    .filter(Boolean);
  console.log(lines.slice(0, 100).join("\n"));

  const editable = await page.locator("[contenteditable='true']").count();
  const buttons = await page.getByRole("button").allTextContents();
  const buttonDetails = await gradingPanel(page)
    .locator("button")
    .evaluateAll((elements) =>
      elements.map((element) => ({
        text: element.textContent?.replace(/\s+/g, " ").trim(),
        ariaLabel: element.getAttribute("aria-label"),
        title: element.getAttribute("title"),
        expanded: element.getAttribute("aria-expanded"),
        visible: Boolean(
          element.offsetWidth ||
            element.offsetHeight ||
            element.getClientRects().length,
        ),
      })),
    );
  const levelCounts = {};
  for (const level of config.rubricLevels) {
    levelCounts[level.label] = await page
      .getByText(level.label, { exact: true })
      .count();
  }
  const scrollables = await page.locator("div, main, section").evaluateAll(
    (elements) =>
      elements
        .filter(
          (element) =>
            element.scrollHeight > element.clientHeight + 20 &&
            getComputedStyle(element).overflowY !== "hidden",
        )
        .map((element) => ({
          tag: element.tagName,
          id: element.id,
          className: element.className,
          role: element.getAttribute("role"),
          ariaLabel: element.getAttribute("aria-label"),
          clientHeight: element.clientHeight,
          scrollHeight: element.scrollHeight,
          text: element.innerText?.slice(0, 160),
        }))
        .slice(0, 30),
  );
  const panels = await page.locator(".bb-offcanvas-panel").evaluateAll(
    (elements) =>
      elements.map((element) => ({
        className: element.className,
        ariaHidden: element.getAttribute("aria-hidden"),
        text: element.innerText?.slice(0, 200),
      })),
  );
  const criterionCommentControls = await gradingPanel(page)
    .locator(
      "[aria-label*='criterio'], [title*='criterio'], button:has-text('no tiene comentario')",
    )
    .evaluateAll((elements) =>
      elements.map((element) => ({
        tag: element.tagName,
        text: element.textContent?.replace(/\s+/g, " ").trim(),
        ariaLabel: element.getAttribute("aria-label"),
        title: element.getAttribute("title"),
        expanded: element.getAttribute("aria-expanded"),
        className: element.className,
      })),
    );
  const criteriaWithComment = (
    visibleText.match(/tiene comentario de texto/g) || []
  ).length;
  const criteriaWithoutComment = (
    visibleText.match(/no tiene comentario de texto/g) || []
  ).length;
  const editors = await gradingPanel(page)
    .locator("textarea, [contenteditable='true'], input")
    .evaluateAll((elements) =>
      elements.map((element) => ({
        tag: element.tagName,
        type: element.getAttribute("type"),
        placeholder: element.getAttribute("placeholder"),
        ariaLabel: element.getAttribute("aria-label"),
        ariaHidden: element.getAttribute("aria-hidden"),
        className: element.className,
        visible: Boolean(
          element.offsetWidth ||
            element.offsetHeight ||
            element.getClientRects().length,
        ),
      })),
    );
  const globalEditors = await page
    .locator("[contenteditable='true'], button[data-analytics-id*='overallFeedback']")
    .evaluateAll((elements) =>
      elements.map((element) => ({
        tag: element.tagName,
        text: element.textContent?.replace(/\s+/g, " ").trim().slice(0, 160),
        ariaLabel: element.getAttribute("aria-label"),
        ariaHidden: element.getAttribute("aria-hidden"),
        className: element.className,
        analyticsId: element.getAttribute("data-analytics-id"),
        visible: Boolean(
          element.offsetWidth ||
            element.offsetHeight ||
            element.getClientRects().length,
        ),
        panelAriaHidden: element
          .closest(".bb-offcanvas-panel")
          ?.getAttribute("aria-hidden"),
        containerText: element.parentElement?.parentElement?.innerText
          ?.replace(/\s+/g, " ")
          .trim()
          .slice(0, 220),
      })),
    );
  console.log(
    JSON.stringify(
      {
        url: page.url(),
        contentEditable: editable,
        levelCounts,
        buttons: buttons.map((text) => text.trim()).filter(Boolean),
        buttonDetails,
        scrollables,
        panels,
        criterionCommentControls,
        editors,
        globalEditors,
        criteriaWithComment,
        criteriaWithoutComment,
      },
      null,
      2,
    ),
  );
}

async function selectStudent(page, result, config) {
  const panel = gradingPanel(page);
  const exactName = new RegExp(
    `^${result.student.avaName.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}$`,
    "i",
  );

  const preferredScrollers = panel.locator("div[class*='listContainer']");
  const configuredScroller =
    (await preferredScrollers.count()) > 0
      ? preferredScrollers
      : panel.locator("div, main, section");
  const scrollableCandidates = [];
  for (let index = 0; index < (await configuredScroller.count()); index += 1) {
    const candidate = configuredScroller.nth(index);
    const metrics = await candidate
      .evaluate((element) => ({
        clientHeight: element.clientHeight,
        scrollHeight: element.scrollHeight,
        overflowY: getComputedStyle(element).overflowY,
        text: element.innerText?.slice(0, 300) || "",
      }))
      .catch(() => null);
    if (
      metrics &&
      metrics.clientHeight >= 200 &&
      metrics.scrollHeight > metrics.clientHeight + 100 &&
      metrics.overflowY !== "hidden" &&
      /CALIFICACI[ÓO]N|ANTINIR SEPULVEDA/i.test(metrics.text)
    ) {
      scrollableCandidates.push({ candidate, scrollHeight: metrics.scrollHeight });
    }
  }
  scrollableCandidates.sort((a, b) => b.scrollHeight - a.scrollHeight);
  const scroller = scrollableCandidates[0]?.candidate;
  if (!scroller) {
    fail(
      `${result.rut}: no se encontró la lista desplazable; ejecuta npm run inspect`,
    );
  }

  const clickVisibleListName = async () => {
    const matches = scroller.getByText(exactName);
    for (let index = 0; index < (await matches.count()); index += 1) {
      const candidate = matches.nth(index);
      if (await candidate.isVisible().catch(() => false)) {
        await candidate.scrollIntoViewIfNeeded();
        await candidate.click();
        await page.waitForTimeout(config.navigationDelayMs);
        return true;
      }
    }
    return false;
  };

  const scrollMetrics = await scroller.evaluate((element) => ({
    max: Math.max(0, element.scrollHeight - element.clientHeight),
  }));
  const steps = Math.min(config.maxStudentScrolls, 40);
  const seenNames = new Set();
  for (let step = 0; step <= steps; step += 1) {
    await scroller.evaluate(
      (element, position) => {
        element.scrollTop = position;
        element.dispatchEvent(new Event("scroll", { bubbles: true }));
      },
      Math.round((scrollMetrics.max * step) / steps),
    );
    await page.waitForTimeout(400);
    for (const text of await scroller.locator("bdi").allTextContents()) {
      const normalized = text.replace(/\s+/g, " ").trim();
      if (normalized.includes(",")) seenNames.add(normalized);
    }
    if (await clickVisibleListName()) return;
  }
  if (await clickVisibleListName()) return;
  fail(
    `${result.rut}: no se encontró en AVA como "${result.student.avaName}". ` +
      `Nombres observados: ${[...seenNames].join(" | ")}`,
  );
}

async function rubricOptionCounts(page, config) {
  const panel = gradingPanel(page);
  const counts = {};
  for (const level of config.rubricLevels) {
    counts[level.label] = await panel
      .getByText(level.label, { exact: true })
      .count();
  }
  return counts;
}

async function openRubric(page, config) {
  const panel = gradingPanel(page);
  const visibleLevel = panel
    .getByText(config.rubricLevels[0].label, { exact: true })
    .first();
  if (await visibleLevel.isVisible().catch(() => false)) {
    return panel.getByText(config.text.rubricHeading, { exact: true }).first();
  }

  const openRubricButton = panel
    .getByRole("button", { name: "Abrir rúbrica", exact: true })
    .first();
  if (await openRubricButton.isVisible().catch(() => false)) {
    await openRubricButton.click();
    await page.waitForTimeout(config.navigationDelayMs);
  }

  let heading = panel
    .getByText(config.text.rubricHeading, { exact: true })
    .first();
  if (await heading.isVisible().catch(() => false)) {
    const headingButton = panel
      .locator("button[aria-expanded]")
      .filter({ hasText: new RegExp(`^${config.text.rubricHeading}`) })
      .first();
    if (
      (await headingButton.count()) > 0 &&
      (await headingButton.getAttribute("aria-expanded")) !== "true"
    ) {
      await headingButton.click();
      await page.waitForTimeout(config.navigationDelayMs);
    }
    return heading;
  }

  if (!(await openRubricButton.isVisible().catch(() => false))) {
    fail("no se encontró el botón Abrir rúbrica");
  }
  await openRubricButton.click();
  heading = panel
    .getByText(config.text.rubricHeading, { exact: true })
    .first();
  await heading.waitFor();
  const headingButton = panel
    .locator("button[aria-expanded]")
    .filter({ hasText: new RegExp(`^${config.text.rubricHeading}`) })
    .first();
  if (
    (await headingButton.count()) > 0 &&
    (await headingButton.getAttribute("aria-expanded")) !== "true"
  ) {
    await headingButton.click();
    await page.waitForTimeout(config.navigationDelayMs);
  }
  return heading;
}

function convertLevel(percent, config, policy) {
  if (!Number.isFinite(percent)) fail(`porcentaje de desempeño inválido: ${percent}`);
  const levels = [...config.rubricLevels].sort((a, b) => b.percent - a.percent);
  const exact = levels.find((level) => Math.abs(level.percent - percent) < 0.01);
  if (exact) return exact;
  if (policy === "floor") {
    return levels.find((level) => level.percent <= percent) || levels.at(-1);
  }
  if (policy === "nearest") {
    return levels.reduce((best, level) =>
      Math.abs(level.percent - percent) < Math.abs(best.percent - percent)
        ? level
        : best,
    );
  }
  fail(
    `${percent}% no existe en AVA; usa --conversion floor o --conversion nearest, o recalifica el IE`,
  );
}

function rubricSummaryPoints(text) {
  const normalized = String(text ?? "")
    .replace(/\u00a0/g, " ")
    .replace(/\s+/g, " ");
  const match = normalized.match(
    /% de la calificación total\s*(\d+(?:[.,]\d+)?)/i,
  );
  return match ? Number(match[1].replace(",", ".")) : Number.NaN;
}

async function waitForRubricSummaryPoints(
  page,
  summary,
  expectedPoints,
  timeoutMs,
) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    const visiblePoints = rubricSummaryPoints(await summary.innerText());
    if (
      Number.isFinite(visiblePoints) &&
      Math.abs(visiblePoints - Number(expectedPoints)) < 0.01
    ) {
      return;
    }
    await page.waitForTimeout(250);
  }
  fail(`AVA no confirmó ${expectedPoints} puntos en el criterio`);
}

async function fillGeneralFeedback(page, feedback, config) {
  if (!feedback) return false;
  const panel = gradingPanel(page);
  const heading = panel.locator("#overall-feedback-button").first();
  await heading.waitFor({ state: "visible" });
  await heading.scrollIntoViewIfNeeded();

  const existingEditButton = panel
    .getByRole("button", { name: "Editar comentarios generales", exact: true })
    .first();
  if (await existingEditButton.isVisible().catch(() => false)) {
    console.log("feedback general ya presente");
    return false;
  }
  const panelText = await panel.innerText();
  const feedbackFingerprint = normalizeText(feedback).slice(0, 100);
  if (
    feedbackFingerprint.length >= 40 &&
    normalizeText(panelText).includes(feedbackFingerprint)
  ) {
    console.log("feedback general ya presente");
    return false;
  }
  if ((await heading.getAttribute("aria-expanded")) !== "true") {
    await heading.click();
    await page.waitForTimeout(500);
  }

  const editor = panel
    .locator(
      "#bb-editor-textbox[contenteditable='true'], " +
        ".ql-editor.bb-editor[contenteditable='true'][aria-labelledby^='overall-feedback-button']",
    )
    .first();
  await editor.waitFor({ state: "visible" });
  await editor.fill(feedback);
  const writtenFeedback = (await editor.innerText()).trim();
  if (normalizeText(writtenFeedback) !== normalizeText(feedback)) {
    fail(
      `no se confirmó el feedback general: esperado=${feedback.length} caracteres, editor=${writtenFeedback.length}`,
    );
  }

  const save = panel
    .locator(
      "button[data-analytics-id='attemptGrading.page.body.overallFeedback.saveButton']:visible",
    )
    .first();
  if ((await save.count()) === 0) {
    fail("no se encontró el botón Guardar del feedback general");
  }
  await save.waitFor({ state: "visible" });
  if (await save.isDisabled()) {
    fail("el botón Guardar del feedback general permaneció deshabilitado");
  }
  await save.click();
  await page.waitForTimeout(config.saveDelayMs);
  await page.waitForFunction(
    ({ fingerprint }) => {
      const panels = [
        ...document.querySelectorAll(
          ".bb-offcanvas-panel.flexible-attempt-grading-panel[aria-hidden='false']",
        ),
      ];
      const activePanel = panels.at(-1);
      if (!activePanel) return false;
      const normalized = (activePanel.innerText || "")
        .normalize("NFD")
        .replace(/\p{Diacritic}/gu, "")
        .replace(/\s+/g, " ")
        .trim()
        .toUpperCase();
      return normalized.includes(fingerprint);
    },
    { fingerprint: feedbackFingerprint },
  );
  console.log("feedback general guardado");
  return true;
}

async function fillRubric(page, result, config, conversionPolicy) {
  const panel = gradingPanel(page);
  await openRubric(page, config);
  await page.waitForFunction(
    ({ expected }) => {
      const panel = document.querySelector(
        ".bb-offcanvas-panel.flexible-attempt-grading-panel[aria-hidden='false']",
      );
      if (!panel) return false;
      const criteria = [...panel.querySelectorAll("button[aria-expanded]")].filter(
        (button) => /% de la calificación total/.test(button.textContent || ""),
      );
      return criteria.length === expected;
    },
    { expected: result.ies.length },
  );

  const criterionSummaries = panel
    .locator("button.MuiAccordionSummary-root[aria-expanded]")
    .filter({ hasText: /% de la calificación total/ });
  if ((await criterionSummaries.count()) !== result.ies.length) {
    fail(
      `${result.rut}: export=${result.ies.length} IE, AVA acordeones=${await criterionSummaries.count()}`,
    );
  }
  const firstSummary = criterionSummaries.first();
  if ((await firstSummary.getAttribute("aria-expanded")) !== "true") {
    await firstSummary.click();
    await page.waitForTimeout(300);
  }
  await panel
    .getByText(config.rubricLevels[0].label, { exact: true })
    .first()
    .waitFor();

  const counts = await rubricOptionCounts(page, config);
  for (const level of config.rubricLevels) {
    if (counts[level.label] !== result.ies.length) {
      fail(
        `${result.rut}: export=${result.ies.length} IE, AVA "${level.label}"=${counts[level.label]}`,
      );
    }
  }

  for (let index = 0; index < result.ies.length; index += 1) {
    const ie = result.ies[index];
    const target = convertLevel(ie.levelPercent, config, conversionPolicy);
    const summary = criterionSummaries.nth(index);
    await summary.scrollIntoViewIfNeeded();
    if ((await summary.getAttribute("aria-expanded")) !== "true") {
      await summary.click();
    }

    const criterion = summary.locator(
      "xpath=ancestor::*[contains(@class,'MuiAccordion-root')][1]",
    );
    if ((await criterion.count()) === 0) {
      fail(`${result.rut}: no se encontró el contenedor del IE ${ie.id}`);
    }

    if (ie.feedback?.trim()) {
      let editor = criterion
        .locator(".ql-editor[contenteditable='true']:visible")
        .first();
      if ((await editor.count()) === 0) {
        let commentButton = criterion
          .locator("button[title='Agregar comentarios']:visible")
          .first();
        if ((await commentButton.count()) === 0) {
          commentButton = criterion
            .locator(
              "button[aria-label^='Agregar comentarios al criterio:'], " +
                "button[aria-label^='Editar comentarios al criterio:'], " +
                "button[aria-label^='Edite los comentarios de este criterio:']",
            )
            .first();
        }
        if ((await commentButton.count()) === 0) {
          fail(`${result.rut}: no se encontró comentario editable para IE ${ie.id}`);
        }
        await commentButton.scrollIntoViewIfNeeded();
        await commentButton.click();
        editor = criterion
          .locator(".ql-editor[contenteditable='true']:visible")
          .first();
        await editor.waitFor();
      }
      await editor.fill(ie.feedback);
      const writtenFeedback = (await editor.innerText()).trim();
      if (writtenFeedback !== ie.feedback.trim()) {
        fail(`${result.rut}: no se confirmó el feedback del IE ${ie.id}`);
      }
      await editor.press("Tab");
      await page.waitForTimeout(700);
      await summary
        .getByText(/tiene comentario de texto/i)
        .waitFor({ state: "visible" });
      console.log(`${result.rut}: feedback IE ${ie.id} cargado`);
    }

    const option = criterion.getByText(target.label, { exact: true }).first();
    await option.scrollIntoViewIfNeeded();
    await option.click();
    await waitForRubricSummaryPoints(
      page,
      summary,
      ie.awardedPoints,
      Math.min(config.timeoutMs, 10000),
    );
    if ((await summary.getAttribute("aria-expanded")) === "true") {
      await summary.click();
      await page.waitForTimeout(250);
    }
  }
}

async function verifyRubricCriteria(page, result) {
  const summaries = gradingPanel(page)
    .locator("button.MuiAccordionSummary-root[aria-expanded]")
    .filter({ hasText: /% de la calificación total/ });
  if ((await summaries.count()) !== result.ies.length) {
    fail(`${result.rut}: no se pudieron revalidar los 10 IE`);
  }

  for (let index = 0; index < result.ies.length; index += 1) {
    const ie = result.ies[index];
    const text = (await summaries.nth(index).innerText())
      .replace(/\u00a0/g, " ")
      .replace(/\s+/g, " ");
    if (!/tiene comentario de texto/i.test(text)) {
      fail(`${result.rut}: IE ${ie.id} quedó sin feedback`);
    }
    const visiblePoints = rubricSummaryPoints(text);
    if (
      !Number.isFinite(visiblePoints) ||
      Math.abs(visiblePoints - Number(ie.awardedPoints)) >= 0.01
    ) {
      fail(
        `${result.rut}: IE ${ie.id} esperaba ${ie.awardedPoints} puntos y AVA muestra ${Number.isFinite(visiblePoints) ? visiblePoints : "sin puntaje"}`,
      );
    }
  }
  console.log(`${result.rut}: 10 IE verificados individualmente`);
}

async function verifyRubricScore(page, result) {
  const expected = Number(result.score);
  const scorePattern = /(\d+(?:[.,]\d+)?)\s*\/\s*100/g;

  await page.waitForFunction(
    ({ expectedScore }) => {
      const matches = [
        ...document.body.innerText.matchAll(/(\d+(?:[.,]\d+)?)\s*\/\s*100/g),
      ];
      return matches.some(
        (match) =>
          Math.abs(
            Number(match[1].replace(",", ".")) - Number(expectedScore),
          ) < 0.01,
      );
    },
    { expectedScore: expected },
  );

  const visibleText = await gradingPanel(page).innerText();
  const visibleScores = [...visibleText.matchAll(scorePattern)].map((match) =>
    Number(match[1].replace(",", ".")),
  );
  if (!visibleScores.some((score) => Math.abs(score - expected) < 0.01)) {
    fail(
      `${result.rut}: AVA no muestra el total esperado ${expected}/100; visibles=${visibleScores.join(", ")}`,
    );
  }
  console.log(`${result.rut}: total AVA verificado ${expected}/100`);
}

async function saveStudent(page, result, config) {
  const save = gradingPanel(page)
    .locator("button:visible")
    .filter({ hasText: new RegExp(`^${config.text.saveButton}$`, "i") })
    .last();
  if ((await save.count()) === 0) {
    await page.waitForTimeout(config.saveDelayMs);
    console.log(`${result.rut}: autoguardado de rúbrica verificado`);
    return;
  }
  if (await save.isDisabled()) {
    await page.waitForTimeout(config.saveDelayMs);
    console.log(`${result.rut}: autoguardado de rúbrica verificado`);
    return;
  }
  await save.scrollIntoViewIfNeeded();
  await save.waitFor({ state: "visible" });
  await save.click();
  await page.waitForTimeout(config.saveDelayMs);
  console.log(`${result.rut}: guardado solicitado`);
}

async function processStudent(
  page,
  result,
  config,
  commit,
  conversionPolicy,
  directUrl,
  feedbackOnly,
) {
  console.log(`${result.rut}: ${result.student.avaName}`);
  if (!directUrl) await selectStudent(page, result, config);

  if (commit) {
    await fillGeneralFeedback(page, result.finalFeedback, config);
    if (feedbackOnly) {
      return {
        rut: result.rut,
        avaName: result.student.avaName,
        studentUrl: page.url(),
        feedbackOnly: true,
        commit: true,
      };
    }
  }

  const rubricHeading = await openRubric(page, config);
  await rubricHeading.scrollIntoViewIfNeeded();

  const counts = await rubricOptionCounts(page, config);
  const summary = {
    rut: result.rut,
    avaName: result.student.avaName,
    studentUrl: page.url(),
    expectedIes: result.ies.length,
    feedbackIes: result.ies.filter((ie) => ie.feedback?.trim()).length,
    avaLevelOptions: counts,
    targetScore: result.score,
    conversionPolicy,
    commit,
  };
  console.log(JSON.stringify(summary));

  if (!commit) return summary;
  await fillRubric(page, result, config, conversionPolicy);
  await verifyRubricCriteria(page, result);
  await verifyRubricScore(page, result);
  await saveStudent(page, result, config);
  return summary;
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  const config = readJson(CONFIG_PATH, "configuración de AVA");
  validateConfig(config);
  const evaluationId = args.evaluationId || config.evaluationId;
  const conversionPolicy =
    args.conversionPolicy || config.conversionPolicy || "exact";
  const results = loadResults(evaluationId, args.studentRut);

  const windowWidth = Number(config.windowWidth) || 1920;
  const windowHeight = Number(config.windowHeight) || 1080;
  const context = await chromium.launchPersistentContext(SESSION_PATH, {
    headless: args.headless,
    viewport: null,
    screen: {
      width: windowWidth,
      height: windowHeight,
    },
    args: [
      "--start-maximized",
      `--window-size=${windowWidth},${windowHeight}`,
      "--window-position=0,0",
    ],
  });
  context.setDefaultTimeout(config.timeoutMs);
  await addSessionCookie(context, config);
  const page = context.pages()[0] || (await context.newPage());
  if (!args.headless) {
    await page.evaluate(
      ({ width, height }) => {
        window.moveTo(0, 0);
        window.resizeTo(width, height);
      },
      { width: windowWidth, height: windowHeight },
    ).catch(() => {});
  }
  await page.goto(args.directUrl || config.gradebookUrl, {
    waitUntil: "domcontentloaded",
  });
  console.log("Si AVA solicita autenticación, complétala en el navegador.");
  await waitForAva(page, config);
  await expandStudentNavigation(page, config);

  if (args.inspect) {
    if (args.studentRut) {
      const result = results[0];
      await selectStudent(page, result, config);
      const rubricHeading = await openRubric(page, config);
      await rubricHeading.scrollIntoViewIfNeeded();
    }
    await inspectPage(page, config);
    await context.close();
    return;
  }

  const report = [];
  for (const result of results) {
    try {
      report.push(
        await processStudent(
          page,
          result,
          config,
          args.commit,
          conversionPolicy,
          args.directUrl,
          args.feedbackOnly,
        ),
      );
    } catch (error) {
      report.push({
        rut: result.rut,
        avaName: result.student.avaName,
        commit: args.commit,
        error: error.message,
      });
      if (args.commit) break;
    }
  }

  fs.mkdirSync(REPORTS_PATH, { recursive: true });
  const reportPath = path.join(
    REPORTS_PATH,
    `${evaluationId}-${new Date().toISOString().replace(/[:.]/g, "-")}.json`,
  );
  fs.writeFileSync(reportPath, JSON.stringify(report, null, 2));
  console.log(`Reporte: ${reportPath}`);
  await context.close();

  if (report.some((item) => item.error)) process.exitCode = 1;
}

main().catch((error) => {
  console.error(`Error: ${error.stack || error.message}`);
  process.exit(1);
});
