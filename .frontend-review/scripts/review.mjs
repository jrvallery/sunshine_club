#!/usr/bin/env node
import { spawn } from "node:child_process";
import fs from "node:fs/promises";
import path from "node:path";
import process from "node:process";

const root = process.cwd();
const configPath = path.join(root, ".frontend-review", "config.json");

function argValue(name) {
  const index = process.argv.indexOf(name);
  if (index === -1) return "";
  return process.argv[index + 1] || "";
}

function hasArg(name) {
  return process.argv.includes(name);
}

function timestamp() {
  return new Date().toISOString().replace(/[:.]/g, "-");
}

async function readConfig() {
  const raw = await fs.readFile(configPath, "utf8");
  return JSON.parse(raw);
}

function joinUrl(base, routePath) {
  const url = new URL(base);
  if (/^https?:\/\//.test(routePath)) return routePath;
  url.pathname = path.posix.join(url.pathname, routePath);
  if (routePath.endsWith("/") && !url.pathname.endsWith("/")) url.pathname += "/";
  return url.toString();
}

async function waitForUrl(url, timeoutMs) {
  const started = Date.now();
  let lastError = "";
  while (Date.now() - started < timeoutMs) {
    try {
      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), 2500);
      const res = await fetch(url, { method: "GET", signal: controller.signal });
      clearTimeout(timer);
      if (res.status < 500) return;
      lastError = `HTTP ${res.status}`;
    } catch (error) {
      lastError = error.message;
    }
    await new Promise((resolve) => setTimeout(resolve, 1000));
  }
  throw new Error(`Timed out waiting for ${url}: ${lastError}`);
}

async function isUrlReady(url) {
  try {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 2500);
    const res = await fetch(url, { method: "GET", signal: controller.signal });
    clearTimeout(timer);
    return res.status < 500;
  } catch {
    return false;
  }
}

function startServer(command) {
  if (!command) return null;
  const child = spawn(command, {
    shell: true,
    cwd: root,
    stdio: ["ignore", "pipe", "pipe"],
    env: { ...process.env, FORCE_COLOR: "1" }
  });
  child.stdout.on("data", (chunk) => process.stdout.write(chunk));
  child.stderr.on("data", (chunk) => process.stderr.write(chunk));
  child.on("exit", (code, signal) => {
    if (code && code !== 0) console.error(`Frontend review server exited with code ${code}${signal ? ` signal ${signal}` : ""}`);
  });
  return child;
}

async function loadPlaywright() {
  try {
    return await import("@playwright/test");
  } catch {
    try {
      return await import("playwright");
    } catch {
      throw new Error("Playwright is not installed. Run: npm install --save-dev @playwright/test && npx playwright install chromium");
    }
  }
}

async function maybeRunAxe(page) {
  try {
    const axe = await import("@axe-core/playwright");
    const builder = new axe.AxeBuilder({ page });
    const result = await builder.analyze();
    return result.violations.map((violation) => ({
      id: violation.id,
      impact: violation.impact,
      description: violation.description,
      nodes: violation.nodes.length
    }));
  } catch {
    return null;
  }
}

async function collectVisualHeuristics(page) {
  return await page.evaluate(() => {
    const visible = (el) => {
      const style = window.getComputedStyle(el);
      const rect = el.getBoundingClientRect();
      return style.visibility !== "hidden" && style.display !== "none" && rect.width > 0 && rect.height > 0;
    };

    const clippedText = [];
    for (const el of Array.from(document.querySelectorAll("body *"))) {
      if (!visible(el)) continue;
      const text = (el.textContent || "").trim();
      if (!text || text.length < 2) continue;
      if (el.scrollWidth > el.clientWidth + 2 || el.scrollHeight > el.clientHeight + 2) {
        const rect = el.getBoundingClientRect();
        clippedText.push({
          tag: el.tagName.toLowerCase(),
          text: text.slice(0, 80),
          rect: {
            x: Math.round(rect.x),
            y: Math.round(rect.y),
            width: Math.round(rect.width),
            height: Math.round(rect.height)
          }
        });
      }
      if (clippedText.length >= 25) break;
    }

    const brokenImages = Array.from(document.images)
      .filter((img) => visible(img) && (!img.complete || img.naturalWidth === 0))
      .map((img) => img.currentSrc || img.src)
      .slice(0, 25);

    const interactive = Array.from(document.querySelectorAll("button, a, input, select, textarea, [role='button'], [role='link']"))
      .filter(visible)
      .map((el) => {
        const rect = el.getBoundingClientRect();
        return {
          tag: el.tagName.toLowerCase(),
          label: (el.getAttribute("aria-label") || el.textContent || el.getAttribute("placeholder") || "").trim().slice(0, 60),
          rect: {
            left: rect.left,
            top: rect.top,
            right: rect.right,
            bottom: rect.bottom,
            width: rect.width,
            height: rect.height
          }
        };
      });

    const overlaps = [];
    for (let i = 0; i < interactive.length; i += 1) {
      for (let j = i + 1; j < interactive.length; j += 1) {
        const a = interactive[i].rect;
        const b = interactive[j].rect;
        const x = Math.max(0, Math.min(a.right, b.right) - Math.max(a.left, b.left));
        const y = Math.max(0, Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top));
        const area = x * y;
        if (area > 24 && area > Math.min(a.width * a.height, b.width * b.height) * 0.12) {
          overlaps.push({ a: interactive[i], b: interactive[j], area: Math.round(area) });
        }
        if (overlaps.length >= 20) break;
      }
      if (overlaps.length >= 20) break;
    }

    const doc = document.documentElement;
    const horizontalOverflow = Math.max(0, doc.scrollWidth - doc.clientWidth);

    return {
      title: document.title,
      horizontalOverflow,
      brokenImages,
      clippedText,
      overlaps
    };
  });
}

function countIssues(item) {
  return {
    consoleErrors: item.consoleErrors.length,
    failedRequests: item.failedRequests.length,
    horizontalOverflow: item.heuristics.horizontalOverflow > 0 ? 1 : 0,
    brokenImages: item.heuristics.brokenImages.length,
    clippedText: item.heuristics.clippedText.length,
    overlaps: item.heuristics.overlaps.length,
    axeViolations: item.axeViolations ? item.axeViolations.length : 0
  };
}

function markdownReport(config, runDir, results) {
  const lines = [];
  lines.push(`# Frontend Review Report`);
  lines.push("");
  lines.push(`Generated: ${new Date().toISOString()}`);
  lines.push(`Base URL: ${config.readyUrl}`);
  lines.push(`Run directory: ${runDir}`);
  lines.push("");
  lines.push("## Summary");
  lines.push("");
  for (const result of results) {
    const counts = countIssues(result);
    const total = Object.values(counts).reduce((sum, value) => sum + value, 0);
    lines.push(`- ${result.routeName} / ${result.viewportName}: ${total} issue signals`);
  }
  lines.push("");
  lines.push("## Findings");
  for (const result of results) {
    const counts = countIssues(result);
    lines.push("");
    lines.push(`### ${result.routeName} - ${result.viewportName}`);
    lines.push("");
    lines.push(`- URL: ${result.url}`);
    lines.push(`- Screenshot: ${result.screenshot}`);
    if (result.fullPageScreenshot) lines.push(`- Full page: ${result.fullPageScreenshot}`);
    lines.push(`- Console errors: ${counts.consoleErrors}`);
    lines.push(`- Failed requests: ${counts.failedRequests}`);
    lines.push(`- Horizontal overflow: ${result.heuristics.horizontalOverflow}px`);
    lines.push(`- Broken images: ${counts.brokenImages}`);
    lines.push(`- Clipped text candidates: ${counts.clippedText}`);
    lines.push(`- Interactive overlap candidates: ${counts.overlaps}`);
    if (result.axeViolations === null) {
      lines.push("- Axe: skipped; install `@axe-core/playwright` to enable");
    } else {
      lines.push(`- Axe violations: ${counts.axeViolations}`);
    }
    if (result.consoleErrors.length) {
      lines.push("");
      lines.push("Console errors:");
      for (const error of result.consoleErrors.slice(0, 10)) lines.push(`- ${error}`);
    }
    if (result.failedRequests.length) {
      lines.push("");
      lines.push("Failed requests:");
      for (const request of result.failedRequests.slice(0, 10)) lines.push(`- ${request}`);
    }
    if (result.heuristics.clippedText.length) {
      lines.push("");
      lines.push("Clipped text candidates:");
      for (const item of result.heuristics.clippedText.slice(0, 10)) lines.push(`- ${item.tag}: "${item.text}" at ${JSON.stringify(item.rect)}`);
    }
    if (result.axeViolations?.length) {
      lines.push("");
      lines.push("Axe violations:");
      for (const violation of result.axeViolations.slice(0, 10)) lines.push(`- ${violation.id} (${violation.impact || "unknown"}): ${violation.description} (${violation.nodes} nodes)`);
    }
  }
  lines.push("");
  return lines.join("\n");
}

async function main() {
  const config = await readConfig();
  if (argValue("--url")) config.readyUrl = argValue("--url");
  if (argValue("--route")) config.routes = [{ name: argValue("--route").replace(/[^a-z0-9_-]/gi, "_") || "route", path: argValue("--route") }];
  if (argValue("--start")) config.startCommand = argValue("--start");
  if (hasArg("--no-server")) config.startCommand = "";

  const runDir = path.join(root, ".frontend-review", "runs", timestamp());
  await fs.mkdir(runDir, { recursive: true });

  let server = null;
  try {
    if (config.startCommand && (!config.reuseExistingServer || !(await isUrlReady(config.readyUrl)))) {
      server = startServer(config.startCommand);
    }
    await waitForUrl(config.readyUrl, config.serverTimeoutMs || 90000);
    const { chromium } = await loadPlaywright();
    const browser = await chromium.launch({ headless: true });
    const results = [];

    for (const route of config.routes || []) {
      for (const viewport of config.viewports || []) {
        const context = await browser.newContext({
          viewport: { width: viewport.width, height: viewport.height },
          deviceScaleFactor: 1
        });
        const page = await context.newPage();
        const consoleErrors = [];
        const failedRequests = [];
        page.on("console", (msg) => {
          if (msg.type() === "error") consoleErrors.push(msg.text());
        });
        page.on("pageerror", (error) => consoleErrors.push(error.message));
        page.on("requestfailed", (request) => failedRequests.push(`${request.method()} ${request.url()} ${request.failure()?.errorText || ""}`));
        page.on("response", (response) => {
          if (response.status() >= 400) failedRequests.push(`${response.status()} ${response.url()}`);
        });

        const url = joinUrl(config.readyUrl, route.path || "/");
        await page.goto(url, { waitUntil: config.waitUntil || "domcontentloaded", timeout: 45000 });
        await page.waitForTimeout(500);

        const stem = `${route.name || "route"}-${viewport.name || `${viewport.width}x${viewport.height}`}`.replace(/[^a-z0-9_-]/gi, "_");
        const screenshotPath = path.join(runDir, `${stem}.png`);
        await page.screenshot({ path: screenshotPath });
        let fullPageScreenshot = "";
        if (config.captureFullPage !== false) {
          fullPageScreenshot = path.join(runDir, `${stem}-full.png`);
          await page.screenshot({ path: fullPageScreenshot, fullPage: true });
        }

        const heuristics = await collectVisualHeuristics(page);
        const axeViolations = config.runAxe === false ? null : await maybeRunAxe(page);
        results.push({
          routeName: route.name || route.path || "route",
          viewportName: viewport.name || `${viewport.width}x${viewport.height}`,
          url,
          screenshot: path.relative(root, screenshotPath),
          fullPageScreenshot: fullPageScreenshot ? path.relative(root, fullPageScreenshot) : "",
          consoleErrors,
          failedRequests,
          heuristics,
          axeViolations
        });
        await context.close();
      }
    }

    await browser.close();
    await fs.writeFile(path.join(runDir, "report.json"), JSON.stringify({ config, results }, null, 2));
    await fs.writeFile(path.join(runDir, "report.md"), markdownReport(config, path.relative(root, runDir), results));
    console.log(`Frontend review complete: ${path.relative(root, runDir)}/report.md`);

    const budgets = config.budgets || {};
    let failed = false;
    for (const result of results) {
      const counts = countIssues(result);
      for (const [name, budget] of Object.entries(budgets)) {
        if (typeof budget === "number" && counts[name] > budget) {
          failed = true;
          console.error(`Budget exceeded: ${result.routeName}/${result.viewportName} ${name}=${counts[name]} > ${budget}`);
        }
      }
    }
    if (failed && !hasArg("--no-fail")) process.exitCode = 1;
  } finally {
    if (server) server.kill("SIGTERM");
  }
}

main().catch((error) => {
  console.error(error.stack || error.message);
  process.exit(1);
});
