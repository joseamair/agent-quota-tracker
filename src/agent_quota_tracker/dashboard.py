from __future__ import annotations

import json
import os
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Optional
from urllib.parse import parse_qs, urlparse

from agent_quota_tracker.core import get_all_statuses, poke_all
from agent_quota_tracker.history import get_analytics_summary, get_history_points
from agent_quota_tracker.scheduler import (
    get_schedule_status,
    install_schedule,
    remove_schedule,
)

_update_event = threading.Event()
_server_running = True


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="en" data-theme="dark">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>⚡ AI Agents Quota Dashboard v2</title>
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500;600;700&family=Plus+Jakarta+Sans:wght@400;500;600;700;800&display=swap" rel="stylesheet">
  <style>
    :root, [data-theme="dark"] {
      --bg: #090d16;
      --bg-gradient: radial-gradient(circle at 50% 0%, #171d36 0%, var(--bg) 75%);
      --card-bg: rgba(22, 27, 46, 0.75);
      --card-border: rgba(255, 255, 255, 0.08);
      --card-hover: rgba(30, 38, 64, 0.9);
      --card-hover-border: rgba(255, 255, 255, 0.18);
      --text-main: #f1f5f9;
      --text-muted: #94a3b8;
      --header-title: linear-gradient(to right, #ffffff, #cbd5e1);
      --box-bg: rgba(0, 0, 0, 0.28);
      --bar-bg: rgba(255, 255, 255, 0.08);
      --modal-bg: #111827;
      --modal-border: rgba(255, 255, 255, 0.12);
      --input-bg: rgba(0, 0, 0, 0.35);
      --input-border: rgba(255, 255, 255, 0.12);
      --cyan: #06b6d4;
      --emerald: #10b981;
      --amber: #f59e0b;
      --rose: #f43f5e;
      --indigo: #6366f1;
      --purple: #8b5cf6;
    }

    [data-theme="oled"] {
      --bg: #000000;
      --bg-gradient: #000000;
      --card-bg: rgba(10, 10, 15, 0.96);
      --card-border: rgba(0, 240, 255, 0.2);
      --card-hover: rgba(16, 16, 26, 1);
      --card-hover-border: rgba(0, 240, 255, 0.5);
      --text-main: #ffffff;
      --text-muted: #94a3b8;
      --header-title: linear-gradient(to right, #00f0ff, #ff007f);
      --box-bg: rgba(0, 0, 0, 0.8);
      --bar-bg: rgba(255, 255, 255, 0.06);
      --modal-bg: #050508;
      --modal-border: rgba(0, 240, 255, 0.3);
      --input-bg: #000000;
      --input-border: rgba(0, 240, 255, 0.3);
      --cyan: #00f0ff;
      --emerald: #00ff88;
      --amber: #ffb800;
      --rose: #ff0055;
      --indigo: #7928ca;
      --purple: #d000ff;
    }

    [data-theme="light"] {
      --bg: #f8fafc;
      --bg-gradient: radial-gradient(circle at 50% 0%, #e2e8f0 0%, var(--bg) 75%);
      --card-bg: rgba(255, 255, 255, 0.94);
      --card-border: rgba(15, 23, 42, 0.09);
      --card-hover: rgba(255, 255, 255, 1);
      --card-hover-border: rgba(99, 102, 241, 0.35);
      --text-main: #0f172a;
      --text-muted: #64748b;
      --header-title: linear-gradient(to right, #0f172a, #334155);
      --box-bg: rgba(241, 245, 249, 0.9);
      --bar-bg: rgba(15, 23, 42, 0.06);
      --modal-bg: #ffffff;
      --modal-border: rgba(15, 23, 42, 0.12);
      --input-bg: #f8fafc;
      --input-border: rgba(15, 23, 42, 0.15);
      --cyan: #0284c7;
      --emerald: #059669;
      --amber: #d97706;
      --rose: #e11d48;
      --indigo: #4f46e5;
      --purple: #7c3aed;
    }

    * {
      box-sizing: border-box;
      margin: 0;
      padding: 0;
    }

    body {
      background: var(--bg-gradient);
      background-color: var(--bg);
      color: var(--text-main);
      font-family: 'Plus Jakarta Sans', -apple-system, BlinkMacSystemFont, sans-serif;
      min-height: 100vh;
      padding: 2.25rem 1.5rem;
      transition: background 0.3s ease, color 0.3s ease;
    }

    .container {
      max-width: 1240px;
      margin: 0 auto;
    }

    header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 2.25rem;
      flex-wrap: wrap;
      gap: 1.25rem;
    }

    .header-title {
      display: flex;
      align-items: center;
      gap: 1rem;
    }

    .header-icon {
      width: 48px;
      height: 48px;
      background: linear-gradient(135deg, var(--cyan), var(--indigo));
      border-radius: 14px;
      display: flex;
      align-items: center;
      justify-content: center;
      font-size: 1.5rem;
      box-shadow: 0 8px 24px rgba(6, 182, 212, 0.25);
    }

    h1 {
      font-size: 1.85rem;
      font-weight: 800;
      letter-spacing: -0.02em;
      background: var(--header-title);
      -webkit-background-clip: text;
      -webkit-text-fill-color: transparent;
    }

    .subtitle-row {
      display: flex;
      align-items: center;
      gap: 0.75rem;
      margin-top: 0.25rem;
      flex-wrap: wrap;
    }

    .subtitle {
      font-size: 0.88rem;
      color: var(--text-muted);
    }

    /* SSE Stream Pill */
    .stream-pill {
      display: inline-flex;
      align-items: center;
      gap: 0.4rem;
      font-size: 0.72rem;
      font-weight: 700;
      padding: 0.25rem 0.65rem;
      border-radius: 9999px;
      background: rgba(16, 185, 129, 0.12);
      color: var(--emerald);
      border: 1px solid rgba(16, 185, 129, 0.25);
      transition: all 0.3s ease;
    }

    .stream-pill.fallback {
      background: rgba(245, 158, 11, 0.12);
      color: var(--amber);
      border-color: rgba(245, 158, 11, 0.25);
    }

    .stream-pill.offline {
      background: rgba(244, 63, 94, 0.12);
      color: var(--rose);
      border-color: rgba(244, 63, 94, 0.25);
    }

    .stream-dot {
      width: 7px;
      height: 7px;
      border-radius: 50%;
      background: currentColor;
      box-shadow: 0 0 8px currentColor;
      animation: pulse 1.8s infinite;
    }

    .header-actions {
      display: flex;
      gap: 0.65rem;
      align-items: center;
      flex-wrap: wrap;
    }

    /* Theme Switcher Segmented Control */
    .theme-switcher {
      display: inline-flex;
      background: var(--box-bg);
      border: 1px solid var(--card-border);
      border-radius: 10px;
      padding: 3px;
      gap: 2px;
    }

    .theme-btn {
      cursor: pointer;
      font-family: inherit;
      font-size: 0.75rem;
      font-weight: 600;
      padding: 0.35rem 0.65rem;
      border-radius: 7px;
      border: none;
      background: transparent;
      color: var(--text-muted);
      transition: all 0.2s ease;
    }

    .theme-btn:hover {
      color: var(--text-main);
    }

    .theme-btn.active {
      background: var(--card-bg);
      color: var(--text-main);
      box-shadow: 0 2px 6px rgba(0, 0, 0, 0.2);
    }

    button {
      cursor: pointer;
      font-family: inherit;
      font-size: 0.85rem;
      font-weight: 600;
      padding: 0.6rem 1.15rem;
      border-radius: 10px;
      border: 1px solid var(--card-border);
      transition: all 0.2s ease;
      display: inline-flex;
      align-items: center;
      gap: 0.45rem;
      user-select: none;
    }

    button:disabled {
      opacity: 0.6;
      cursor: not-allowed;
    }

    .btn-primary {
      background: linear-gradient(135deg, #0ea5e9, #6366f1);
      color: white;
      border: none;
      box-shadow: 0 4px 16px rgba(14, 165, 233, 0.3);
    }

    .btn-primary:hover:not(:disabled) {
      transform: translateY(-1px);
      box-shadow: 0 6px 20px rgba(14, 165, 233, 0.45);
    }

    .btn-secondary {
      background: var(--card-bg);
      color: var(--text-main);
    }

    .btn-secondary:hover:not(:disabled) {
      background: var(--card-hover);
      border-color: var(--card-hover-border);
    }

    /* Stats Summary */
    .stats-summary {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 1.25rem;
      margin-bottom: 2rem;
    }

    .stat-card {
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      border-radius: 16px;
      padding: 1.25rem 1.5rem;
      backdrop-filter: blur(12px);
      transition: transform 0.2s ease, border-color 0.2s ease;
    }

    .stat-card:hover {
      border-color: var(--card-hover-border);
      transform: translateY(-1px);
    }

    .stat-label {
      font-size: 0.78rem;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      color: var(--text-muted);
      margin-bottom: 0.4rem;
    }

    .stat-value {
      font-size: 1.75rem;
      font-weight: 700;
      font-family: 'JetBrains Mono', monospace;
    }

    /* Agent Cards Grid */
    .grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(350px, 1fr));
      gap: 1.5rem;
    }

    .agent-card {
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      border-radius: 18px;
      padding: 1.5rem;
      backdrop-filter: blur(12px);
      transition: all 0.25s ease;
      position: relative;
      overflow: hidden;
      display: flex;
      flex-direction: column;
      justify-content: space-between;
    }

    .agent-card:hover {
      border-color: var(--card-hover-border);
      background: var(--card-hover);
      transform: translateY(-2px);
    }

    .agent-card.card-exhausted {
      border-color: rgba(244, 63, 94, 0.4);
    }

    .card-top {
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      margin-bottom: 1.25rem;
    }

    .agent-title {
      font-size: 1.15rem;
      font-weight: 700;
      display: flex;
      align-items: center;
      gap: 0.5rem;
    }

    .provider-tag {
      font-size: 0.68rem;
      font-weight: 700;
      text-transform: uppercase;
      padding: 0.2rem 0.5rem;
      border-radius: 6px;
      background: var(--bar-bg);
      color: var(--text-muted);
    }

    .status-badges-group {
      display: flex;
      flex-direction: column;
      align-items: flex-end;
      gap: 0.35rem;
    }

    .status-badge {
      display: inline-flex;
      align-items: center;
      gap: 0.4rem;
      font-size: 0.72rem;
      font-weight: 700;
      padding: 0.3rem 0.7rem;
      border-radius: 9999px;
      text-transform: uppercase;
      letter-spacing: 0.04em;
    }

    .badge-active {
      background: rgba(16, 185, 129, 0.15);
      color: var(--emerald);
      border: 1px solid rgba(16, 185, 129, 0.3);
    }

    .badge-active::before {
      content: "";
      width: 7px;
      height: 7px;
      border-radius: 50%;
      background: var(--emerald);
      box-shadow: 0 0 8px var(--emerald);
      animation: pulse 1.8s infinite;
    }

    .badge-inactive {
      background: rgba(148, 163, 184, 0.12);
      color: var(--text-muted);
      border: 1px solid rgba(148, 163, 184, 0.2);
    }

    .badge-exhausted {
      background: rgba(244, 63, 94, 0.18);
      color: var(--rose);
      border: 1px solid rgba(244, 63, 94, 0.35);
      font-size: 0.68rem;
      padding: 0.2rem 0.55rem;
    }

    @keyframes pulse {
      0%, 100% { opacity: 1; transform: scale(1); }
      50% { opacity: 0.4; transform: scale(0.85); }
    }

    .window-timer-box {
      background: var(--box-bg);
      border-radius: 12px;
      padding: 1rem 1.25rem;
      margin-bottom: 1.25rem;
      display: flex;
      justify-content: space-between;
      align-items: center;
    }

    .timer-info-col {
      display: flex;
      flex-direction: column;
    }

    .timer-label {
      font-size: 0.72rem;
      color: var(--text-muted);
      text-transform: uppercase;
      letter-spacing: 0.05em;
      margin-bottom: 0.2rem;
    }

    .timer-value {
      font-family: 'JetBrains Mono', monospace;
      font-size: 1.45rem;
      font-weight: 700;
      color: var(--cyan);
    }

    .timer-value.inactive {
      color: var(--text-muted);
      font-size: 1.15rem;
    }

    .reset-info-col {
      text-align: right;
    }

    .reset-time-sub {
      font-size: 0.8rem;
      font-family: 'JetBrains Mono', monospace;
      color: var(--text-main);
    }

    .progress-section {
      margin-bottom: 1.15rem;
    }

    .progress-labels {
      display: flex;
      justify-content: space-between;
      font-size: 0.78rem;
      margin-bottom: 0.4rem;
    }

    .progress-pct {
      font-family: 'JetBrains Mono', monospace;
      font-weight: 700;
    }

    .progress-bar-bg {
      height: 8px;
      background: var(--bar-bg);
      border-radius: 9999px;
      overflow: hidden;
      position: relative;
    }

    .progress-bar-fill {
      height: 100%;
      border-radius: 9999px;
      transition: width 0.4s ease;
    }

    .fill-low {
      background: linear-gradient(90deg, #10b981, #06b6d4);
    }

    .fill-med {
      background: linear-gradient(90deg, #06b6d4, #f59e0b);
    }

    .fill-high {
      background: linear-gradient(90deg, #f59e0b, #f43f5e);
    }

    .fill-exhausted {
      background: linear-gradient(90deg, #f43f5e, #dc2626);
    }

    .weekly-box {
      margin-top: 0.75rem;
      padding-top: 0.75rem;
      border-top: 1px solid var(--card-border);
      font-size: 0.78rem;
      color: var(--text-muted);
    }

    .weekly-labels {
      display: flex;
      justify-content: space-between;
      margin-bottom: 0.35rem;
    }

    .weekly-footer {
      display: flex;
      justify-content: space-between;
      font-size: 0.75rem;
      margin-top: 0.35rem;
    }

    .card-footer {
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding-top: 0.85rem;
      border-top: 1px solid var(--card-border);
      font-size: 0.78rem;
      color: var(--text-muted);
      margin-top: 0.75rem;
    }

    .btn-poke-card {
      padding: 0.45rem 0.9rem;
      font-size: 0.75rem;
      border-radius: 8px;
      background: var(--bar-bg);
      color: var(--text-main);
      border: 1px solid var(--card-border);
    }

    .btn-poke-card:hover:not(:disabled) {
      background: var(--cyan);
      color: #000;
      border-color: var(--cyan);
    }

    .btn-poke-card.force-mode {
      background: rgba(244, 63, 94, 0.18);
      color: var(--rose);
      border-color: rgba(244, 63, 94, 0.4);
    }

    .btn-poke-card.force-mode:hover:not(:disabled) {
      background: var(--rose);
      color: white;
    }

    /* Modal */
    .modal-backdrop {
      position: fixed;
      top: 0;
      left: 0;
      width: 100vw;
      height: 100vh;
      background: rgba(0, 0, 0, 0.7);
      backdrop-filter: blur(8px);
      z-index: 10000;
      display: flex;
      align-items: center;
      justify-content: center;
      padding: 1.5rem;
      opacity: 0;
      pointer-events: none;
      transition: opacity 0.25s ease;
    }

    .modal-backdrop.open {
      opacity: 1;
      pointer-events: auto;
    }

    .modal {
      background: var(--modal-bg);
      border: 1px solid var(--modal-border);
      border-radius: 20px;
      width: 100%;
      max-width: 520px;
      padding: 2rem;
      box-shadow: 0 25px 60px rgba(0, 0, 0, 0.6);
      transform: scale(0.95);
      transition: transform 0.25s ease;
    }

    .modal-backdrop.open .modal {
      transform: scale(1);
    }

    .modal-header {
      display: flex;
      justify-content: space-between;
      align-items: flex-start;
      margin-bottom: 1.25rem;
    }

    .modal-title {
      font-size: 1.35rem;
      font-weight: 800;
    }

    .modal-close {
      background: transparent;
      border: none;
      font-size: 1.25rem;
      color: var(--text-muted);
      cursor: pointer;
      padding: 0.25rem;
    }

    .modal-close:hover {
      color: var(--text-main);
    }

    .status-panel {
      background: var(--box-bg);
      border-radius: 12px;
      padding: 1rem;
      margin-bottom: 1.5rem;
      font-size: 0.82rem;
      line-height: 1.6;
    }

    .form-group {
      margin-bottom: 1.25rem;
    }

    .form-label {
      display: block;
      font-size: 0.8rem;
      font-weight: 600;
      color: var(--text-muted);
      margin-bottom: 0.4rem;
      text-transform: uppercase;
      letter-spacing: 0.04em;
    }

    .form-control {
      width: 100%;
      padding: 0.65rem 0.9rem;
      background: var(--input-bg);
      border: 1px solid var(--input-border);
      border-radius: 10px;
      color: var(--text-main);
      font-family: inherit;
      font-size: 0.9rem;
      outline: none;
    }

    .form-control:focus {
      border-color: var(--cyan);
    }

    .form-checkbox {
      display: flex;
      align-items: center;
      gap: 0.6rem;
      font-size: 0.85rem;
      cursor: pointer;
    }

    .form-checkbox input {
      accent-color: var(--cyan);
      width: 16px;
      height: 16px;
    }

    .modal-actions {
      display: flex;
      justify-content: flex-end;
      gap: 0.75rem;
      margin-top: 1.75rem;
    }

    /* Toast */
    .banner-toast {
      position: fixed;
      bottom: 2rem;
      right: 2rem;
      background: var(--modal-bg);
      color: var(--text-main);
      border: 1px solid var(--modal-border);
      border-radius: 12px;
      padding: 0.9rem 1.35rem;
      box-shadow: 0 12px 36px rgba(0, 0, 0, 0.5);
      z-index: 11000;
      opacity: 0;
      transform: translateY(20px);
      transition: all 0.3s ease;
      display: flex;
      align-items: center;
      gap: 0.75rem;
      font-size: 0.88rem;
      pointer-events: none;
    }

    .banner-toast.show {
      opacity: 1;
      transform: translateY(0);
      pointer-events: auto;
    }

    /* Analytics Section */
    .analytics-section {
      margin-top: 2.25rem;
      background: var(--card-bg);
      border: 1px solid var(--card-border);
      border-radius: 18px;
      padding: 1.75rem;
      box-shadow: 0 10px 30px rgba(0, 0, 0, 0.25);
    }

    .analytics-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      flex-wrap: wrap;
      gap: 1rem;
      margin-bottom: 1.5rem;
      padding-bottom: 1rem;
      border-bottom: 1px solid var(--card-border);
    }

    .analytics-title {
      font-size: 1.25rem;
      font-weight: 800;
      display: flex;
      align-items: center;
      gap: 0.6rem;
    }

    .period-selector {
      display: flex;
      gap: 0.4rem;
      background: var(--box-bg);
      padding: 0.25rem;
      border-radius: 10px;
      border: 1px solid var(--card-border);
    }

    .period-btn {
      padding: 0.35rem 0.75rem;
      font-size: 0.78rem;
      font-weight: 600;
      border-radius: 6px;
      background: transparent;
      color: var(--text-muted);
      border: none;
      cursor: pointer;
      transition: all 0.2s ease;
    }

    .period-btn:hover {
      color: var(--text-main);
    }

    .period-btn.active {
      background: var(--cyan);
      color: #000;
      font-weight: 700;
    }

    .analytics-summary-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
      gap: 1rem;
      margin-bottom: 1.5rem;
    }

    .analytics-metric-card {
      background: var(--box-bg);
      border: 1px solid var(--card-border);
      border-radius: 12px;
      padding: 1rem 1.2rem;
    }

    .analytics-metric-label {
      font-size: 0.75rem;
      font-weight: 600;
      color: var(--text-muted);
      text-transform: uppercase;
      letter-spacing: 0.05em;
      margin-bottom: 0.35rem;
    }

    .analytics-metric-value {
      font-size: 1.35rem;
      font-weight: 800;
      font-family: 'JetBrains Mono', monospace;
    }

    .analytics-metric-sub {
      font-size: 0.72rem;
      color: var(--text-muted);
      margin-top: 0.35rem;
    }

    .chart-box {
      background: var(--box-bg);
      border: 1px solid var(--card-border);
      border-radius: 14px;
      padding: 1.25rem;
      margin-bottom: 1.5rem;
    }

    .chart-box-header {
      display: flex;
      justify-content: space-between;
      align-items: center;
      flex-wrap: wrap;
      gap: 0.75rem;
      margin-bottom: 1rem;
    }

    .chart-box-title {
      font-size: 0.95rem;
      font-weight: 700;
    }

    .chart-legend {
      display: flex;
      flex-wrap: wrap;
      gap: 0.85rem;
      font-size: 0.75rem;
    }

    .legend-item {
      display: flex;
      align-items: center;
      gap: 0.4rem;
    }

    .legend-dot {
      width: 10px;
      height: 10px;
      border-radius: 50%;
    }

    .hourly-grid {
      display: flex;
      align-items: flex-end;
      gap: 4px;
      height: 90px;
      padding-top: 15px;
    }

    .hourly-bar-col {
      flex: 1;
      display: flex;
      flex-direction: column;
      align-items: center;
      height: 100%;
      justify-content: flex-end;
      position: relative;
    }

    .hourly-bar {
      width: 100%;
      border-radius: 4px 4px 0 0;
      background: rgba(6, 182, 212, 0.4);
      min-height: 4px;
      transition: height 0.4s ease, background 0.2s ease;
    }

    .hourly-bar.peak {
      background: var(--cyan);
      box-shadow: 0 0 8px rgba(6, 182, 212, 0.5);
    }

    .hourly-bar-label {
      font-size: 0.65rem;
      color: var(--text-muted);
      margin-top: 4px;
      font-family: 'JetBrains Mono', monospace;
    }
  </style>
</head>
<body>
  <div class="container">
    <header>
      <div class="header-title">
        <div class="header-icon">⚡</div>
        <div>
          <h1>AI Agents Quota Dashboard</h1>
          <div class="subtitle-row">
            <span class="subtitle">Real-time status across Claude (CCS), Codex, and Google Antigravity</span>
            <div class="stream-pill" id="stream-indicator">
              <span class="stream-dot"></span>
              <span id="stream-status">Connecting SSE...</span>
            </div>
          </div>
        </div>
      </div>
      <div class="header-actions">
        <div class="theme-switcher">
          <button class="theme-btn" data-theme="dark" onclick="setTheme('dark')">🌙 Dark</button>
          <button class="theme-btn" data-theme="oled" onclick="setTheme('oled')">⚡ OLED</button>
          <button class="theme-btn" data-theme="light" onclick="setTheme('light')">☀️ Light</button>
        </div>
        <button class="btn-secondary" onclick="openScheduleModal()">⏰ Morning Priming</button>
        <button class="btn-secondary" onclick="fetchData(true)">🔄 Refresh</button>
        <button class="btn-primary" id="btn-poke-all" onclick="triggerPokeAll()">⚡ Poke All Idle</button>
      </div>
    </header>

    <div class="stats-summary">
      <div class="stat-card">
        <div class="stat-label">Active Windows</div>
        <div class="stat-value" id="summary-active" style="color: var(--emerald);">- / -</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Idle / Ready to Poke</div>
        <div class="stat-value" id="summary-inactive" style="color: var(--amber);">-</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Next Reset Coming In</div>
        <div class="stat-value" id="summary-next-reset" style="color: var(--cyan);">-</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">System Monitoring</div>
        <div class="stat-value" id="summary-total" style="color: var(--indigo);">- Agents</div>
      </div>
    </div>

    <div class="grid" id="agents-grid">
      <!-- Agent cards injected dynamically -->
    </div>

    <!-- Historical Analytics & Burn-Down Section -->
    <section class="analytics-section">
      <div class="analytics-header">
        <div class="analytics-title">
          <span>📊 Quota Velocity &amp; Burn-Down Analytics</span>
          <span style="font-size: 0.75rem; font-weight: normal; color: var(--text-muted);">Historical SQLite Timeseries</span>
        </div>
        <div class="period-selector">
          <button class="period-btn" onclick="changeAnalyticsPeriod(1, this)">24h</button>
          <button class="period-btn" onclick="changeAnalyticsPeriod(3, this)">3 Days</button>
          <button class="period-btn active" onclick="changeAnalyticsPeriod(7, this)">7 Days</button>
          <button class="period-btn" onclick="changeAnalyticsPeriod(14, this)">14 Days</button>
          <button class="period-btn" onclick="triggerBackfill(this)" title="Import past morning priming and poke events from legacy logs">📥 Backfill</button>
        </div>
      </div>

      <div class="analytics-summary-grid">
        <div class="analytics-metric-card">
          <div class="analytics-metric-label">Active Time Ratio</div>
          <div class="analytics-metric-value" id="ana-active-ratio" style="color: var(--emerald);">0.0%</div>
          <div class="analytics-metric-sub">Percent of tracked time active</div>
        </div>
        <div class="analytics-metric-card">
          <div class="analytics-metric-label">Peak Usage Hours</div>
          <div class="analytics-metric-value" id="ana-peak-hours" style="color: var(--cyan); font-size: 1.1rem;">-</div>
          <div class="analytics-metric-sub">Highest prompt consumption block</div>
        </div>
        <div class="analytics-metric-card">
          <div class="analytics-metric-label">Optimal Morning Priming</div>
          <div class="analytics-metric-value" id="ana-rec-time" style="color: var(--amber);">⚡ 07:30</div>
          <div class="analytics-metric-sub" id="ana-rec-reason">Aligns 5h window for midday reset</div>
        </div>
        <div class="analytics-metric-card">
          <div class="analytics-metric-label">Logged Snapshots</div>
          <div class="analytics-metric-value" id="ana-events" style="color: var(--indigo);">0 snaps</div>
          <div class="analytics-metric-sub" id="ana-pokes">0 verified pokes</div>
        </div>
      </div>

      <!-- Burn-Down Velocity Chart -->
      <div class="chart-box">
        <div class="chart-box-header">
          <div class="chart-box-title">⚡ 5-Hour Quota Utilization Burn-Down &amp; Velocity</div>
          <div class="chart-legend" id="chart-legend"></div>
        </div>
        <div id="chart-container" style="position: relative; width: 100%; min-height: 200px;"></div>
      </div>

      <!-- 24-Hour Activity Distribution Heatmap -->
      <div class="chart-box" style="margin-bottom: 0;">
        <div class="chart-box-header">
          <div class="chart-box-title">🕒 24-Hour Diurnal Activity Distribution</div>
          <div style="font-size: 0.75rem; color: var(--text-muted);">Hourly event density (local time)</div>
        </div>
        <div class="hourly-grid" id="hourly-bars"></div>
      </div>
    </section>
  </div>

  <!-- Scheduled Morning Priming Modal -->
  <div class="modal-backdrop" id="schedule-modal" onclick="closeScheduleModal(event)">
    <div class="modal" onclick="event.stopPropagation()">
      <div class="modal-header">
        <div>
          <div class="modal-title">⏰ Morning Priming Scheduler</div>
          <div class="subtitle" style="margin-top: 0.2rem;">OS-Level unattended morning quota priming</div>
        </div>
        <button class="modal-close" onclick="closeScheduleModal()">&times;</button>
      </div>

      <div class="status-panel" id="modal-status-panel">
        <div><b>Status:</b> <span id="sched-status-text">Checking...</span></div>
        <div><b>Platform:</b> <span id="sched-platform-text">-</span></div>
        <div><b>Next Run:</b> <span id="sched-next-run">-</span></div>
        <div><b>Last Run:</b> <span id="sched-last-run">-</span></div>
      </div>

      <form id="schedule-form" onsubmit="saveSchedule(event)">
        <div class="form-group">
          <label class="form-label">Target Wake Time (24h)</label>
          <input type="time" class="form-control" id="sched-time" value="07:30" required>
        </div>

        <div class="form-group">
          <label class="form-label">Recurrence Frequency</label>
          <select class="form-control" id="sched-frequency">
            <option value="daily">Daily (Default)</option>
            <option value="weekdays">Weekdays Only (Mon-Fri)</option>
            <option value="once">Run Once</option>
          </select>
        </div>

        <div class="form-group">
          <label class="form-checkbox">
            <input type="checkbox" id="sched-notify" checked>
            Send native OS desktop toast notifications upon priming
          </label>
        </div>

        <div class="modal-actions">
          <button type="button" class="btn-secondary" id="btn-remove-sched" onclick="removeScheduleTask()" style="display: none; color: var(--rose);">Uninstall Task</button>
          <button type="button" class="btn-secondary" onclick="closeScheduleModal()">Cancel</button>
          <button type="submit" class="btn-primary" id="btn-save-sched">Save &amp; Install Task</button>
        </div>
      </form>
    </div>
  </div>

  <div class="banner-toast" id="toast">
    <span id="toast-icon">ℹ️</span>
    <span id="toast-msg">Notification</span>
  </div>

  <script>
    let agentsData = [];
    let eventSource = null;
    let sseRetryTimer = null;
    let fallbackPollTimer = null;

    function formatSeconds(secs) {
      if (secs <= 0) return "0s";
      const h = Math.floor(secs / 3600);
      const m = Math.floor((secs % 3600) / 60);
      const s = Math.floor(secs % 60);
      const parts = [];
      if (h > 0) parts.push(`${h}h`);
      if (m > 0) parts.push(`${m}m`);
      if (s > 0 || parts.length === 0) parts.push(`${s}s`);
      return parts.join(" ");
    }

    function showToast(msg, icon = "ℹ️") {
      const toast = document.getElementById("toast");
      document.getElementById("toast-msg").innerText = msg;
      document.getElementById("toast-icon").innerText = icon;
      toast.classList.add("show");
      setTimeout(() => toast.classList.remove("show"), 4000);
    }

    // Theme Switcher
    function setTheme(theme) {
      document.documentElement.setAttribute('data-theme', theme);
      localStorage.setItem('agent_quota_tracker_theme', theme);
      document.querySelectorAll('.theme-btn').forEach(btn => {
        btn.classList.toggle('active', btn.getAttribute('data-theme') === theme);
      });
    }

    // Initialize Theme from localStorage
    const savedTheme = localStorage.getItem('agent_quota_tracker_theme') || 'dark';
    setTheme(savedTheme);

    function setStreamStatus(status) {
      const pill = document.getElementById("stream-indicator");
      const label = document.getElementById("stream-status");
      pill.className = "stream-pill";

      if (status === "live") {
        label.innerText = "Live SSE Stream";
      } else if (status === "fallback") {
        pill.classList.add("fallback");
        label.innerText = "Polling (Fallback)";
      } else {
        pill.classList.add("offline");
        label.innerText = "Offline";
      }
    }

    // Server-Sent Events (SSE)
    function connectSSE() {
      if (eventSource) {
        eventSource.close();
      }

      try {
        eventSource = new EventSource('/api/stream');

        eventSource.addEventListener('quota_update', (e) => {
          try {
            agentsData = JSON.parse(e.data);
            setStreamStatus('live');
            render();
            fetchAnalytics();
          } catch (err) {
            console.error("SSE parse error:", err);
          }
        });

        eventSource.onopen = () => {
          setStreamStatus('live');
          if (fallbackPollTimer) {
            clearInterval(fallbackPollTimer);
            fallbackPollTimer = null;
          }
        };

        eventSource.onerror = () => {
          setStreamStatus('fallback');
          eventSource.close();
          eventSource = null;

          if (!fallbackPollTimer) {
            fallbackPollTimer = setInterval(() => fetchData(false), 8000);
          }
          if (!sseRetryTimer) {
            sseRetryTimer = setTimeout(() => {
              sseRetryTimer = null;
              connectSSE();
            }, 6000);
          }
        };
      } catch (err) {
        setStreamStatus('fallback');
      }
    }

    async function fetchData(forceRefresh = false) {
      try {
        const url = forceRefresh ? "/api/status?refresh=true" : "/api/status";
        const res = await fetch(url);
        if (!res.ok) throw new Error("Status endpoint failed");
        agentsData = await res.json();
        render();
        if (forceRefresh) {
          showToast("Refreshed latest quota data from providers", "✔");
          fetchAnalytics();
        }
      } catch (err) {
        console.error("Error fetching status:", err);
      }
    }

    async function triggerPokeAll() {
      const btn = document.getElementById("btn-poke-all");
      btn.disabled = true;
      btn.innerHTML = "⏳ Poking All...";
      showToast("Poking idle agents to prime 5h windows...", "⏳");
      try {
        const res = await fetch("/api/poke", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({})
        });
        const resp = await res.json();
        const results = resp.results || resp;
        const pokedCount = (results || []).filter(r => r.action_taken === "poked" || r.verified_active).length;
        showToast(`Primed ${pokedCount} agent(s) successfully!`, "⚡");
        await fetchData(true);
      } catch (err) {
        showToast("Error triggering poke: " + err.message, "❌");
      } finally {
        btn.disabled = false;
        btn.innerHTML = "⚡ Poke All Idle";
      }
    }

    async function triggerPoke(agentId, force = false) {
      const cardBtn = document.getElementById(`poke-btn-${agentId}`);
      if (cardBtn) {
        cardBtn.disabled = true;
        cardBtn.innerHTML = "⏳ Poking...";
      }
      showToast(`Poking agent ${agentId}...`, "⏳");
      try {
        const res = await fetch("/api/poke", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ agent_id: agentId, force: force })
        });
        const resp = await res.json();
        showToast(`Agent ${agentId} primed successfully!`, "⚡");
        await fetchData(true);
      } catch (err) {
        showToast("Error: " + err.message, "❌");
      } finally {
        if (cardBtn) {
          cardBtn.disabled = false;
          cardBtn.innerHTML = "⚡ Poke";
        }
      }
    }

    function render() {
      const grid = document.getElementById("agents-grid");
      grid.innerHTML = "";

      let activeCount = 0;
      let nextResetSeconds = null;

      agentsData.forEach(agent => {
        const isExhausted = (agent.weekly_used_percent !== null && agent.weekly_used_percent >= 100.0);

        if (agent.is_active) {
          activeCount++;
          if (agent.time_remaining_seconds > 0) {
            if (nextResetSeconds === null || agent.time_remaining_seconds < nextResetSeconds) {
              nextResetSeconds = agent.time_remaining_seconds;
            }
          }
        }

        const card = document.createElement("div");
        card.className = `agent-card ${isExhausted ? 'card-exhausted' : ''}`;

        const fillClass = isExhausted ? "fill-exhausted" : (agent.used_percent > 80 ? "fill-high" : (agent.used_percent > 50 ? "fill-med" : "fill-low"));
        const statusBadge = agent.is_active
          ? `<span class="status-badge badge-active">Active</span>`
          : `<span class="status-badge badge-inactive">Inactive</span>`;

        const exhaustedBadge = isExhausted
          ? `<span class="status-badge badge-exhausted">⚠️ 100% Weekly</span>`
          : ``;

        let resetFormatted = "Ready for trigger";
        if (agent.resets_at) {
          const d = new Date(agent.resets_at);
          resetFormatted = d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
        }

        const timerClass = agent.is_active ? "timer-value" : "timer-value inactive";
        const timerText = agent.is_active ? formatSeconds(agent.time_remaining_seconds) : "Window Inactive";

        const pokeBtnLabel = isExhausted ? "⚡ Force Poke" : "⚡ Poke";
        const pokeBtnClass = isExhausted ? "btn-poke-card force-mode" : "btn-poke-card";

        card.innerHTML = `
          <div>
            <div class="card-top">
              <div>
                <div class="agent-title">
                  ${agent.name}
                </div>
                <span class="provider-tag">${agent.provider}</span>
              </div>
              <div class="status-badges-group">
                ${statusBadge}
                ${exhaustedBadge}
              </div>
            </div>

            <div class="window-timer-box">
              <div class="timer-info-col">
                <span class="timer-label">5h Window Left</span>
                <span class="${timerClass}" id="timer-${agent.id}">${timerText}</span>
              </div>
              <div class="reset-info-col">
                <span class="timer-label">Next Reset</span>
                <span class="reset-time-sub">${resetFormatted}</span>
              </div>
            </div>

            <div class="progress-section">
              <div class="progress-labels">
                <span style="color: var(--text-muted); font-size: 0.75rem;">Account 5h Usage</span>
                <span class="progress-pct" style="color: ${agent.used_percent > 80 ? 'var(--rose)' : 'inherit'}">${agent.used_percent}%</span>
              </div>
              <div class="progress-bar-bg">
                <div class="progress-bar-fill ${fillClass}" style="width: ${Math.min(100, Math.max(2, agent.used_percent))}%"></div>
              </div>
            </div>

            ${agent.weekly_reset_str && agent.weekly_reset_str !== '-' ? `
            <div class="weekly-box">
              <div class="weekly-labels">
                <span style="font-size: 0.75rem;">Weekly Quota:</span>
                <b style="color: ${isExhausted ? 'var(--rose)' : 'inherit'}; font-size: 0.75rem;">${agent.weekly_used_percent !== null ? agent.weekly_used_percent + '%' : '-'}</b>
              </div>
              ${agent.weekly_used_percent !== null ? `
              <div class="progress-bar-bg" style="height: 5px; margin-bottom: 0.45rem;">
                <div class="progress-bar-fill" style="width: ${Math.min(100, Math.max(2, agent.weekly_used_percent))}%; background: ${isExhausted ? 'var(--rose)' : 'linear-gradient(90deg, #38bdf8, #818cf8)'};"></div>
              </div>` : ''}
              <div class="weekly-footer">
                <span>Weekly Reset:</span>
                <span style="color: ${isExhausted ? 'var(--rose)' : 'var(--cyan)'}; font-weight: 600;">${agent.weekly_reset_str}</span>
              </div>
            </div>` : ''}
          </div>

          <div class="card-footer">
            <span>${agent.category ? agent.category.toUpperCase() : 'AGENT'}</span>
            <button class="${pokeBtnClass}" id="poke-btn-${agent.id}" onclick="triggerPoke('${agent.id}', ${isExhausted})">${pokeBtnLabel}</button>
          </div>
        `;

        grid.appendChild(card);
      });

      // Update Summary cards
      document.getElementById("summary-active").innerText = `${activeCount} / ${agentsData.length}`;
      document.getElementById("summary-inactive").innerText = `${agentsData.length - activeCount}`;
      document.getElementById("summary-next-reset").innerText = nextResetSeconds !== null ? formatSeconds(nextResetSeconds) : "None active";
      document.getElementById("summary-total").innerText = `${agentsData.length} Monitored`;
    }

    function tickTimers() {
      if (!agentsData || agentsData.length === 0) return;
      let minReset = null;

      agentsData.forEach(agent => {
        if (agent.is_active && agent.time_remaining_seconds > 0) {
          agent.time_remaining_seconds--;
          const el = document.getElementById(`timer-${agent.id}`);
          if (el) {
            el.innerText = formatSeconds(agent.time_remaining_seconds);
          }
          if (minReset === null || agent.time_remaining_seconds < minReset) {
            minReset = agent.time_remaining_seconds;
          }
        }
      });

      if (minReset !== null) {
        document.getElementById("summary-next-reset").innerText = formatSeconds(minReset);
      }
    }

    // Scheduled Priming Modal Logic
    async function openScheduleModal() {
      const modal = document.getElementById("schedule-modal");
      modal.classList.add("open");
      await loadScheduleStatus();
    }

    function closeScheduleModal(event) {
      if (event && event.target !== event.currentTarget) return;
      document.getElementById("schedule-modal").classList.remove("open");
    }

    async function loadScheduleStatus() {
      try {
        const res = await fetch("/api/schedule");
        const data = await res.json();
        const statusText = document.getElementById("sched-status-text");
        const platformText = document.getElementById("sched-platform-text");
        const nextRun = document.getElementById("sched-next-run");
        const lastRun = document.getElementById("sched-last-run");
        const removeBtn = document.getElementById("btn-remove-sched");

        platformText.innerText = data.platform ? data.platform.toUpperCase() : "OS Default";
        nextRun.innerText = data.next_run_time || "None";
        lastRun.innerText = data.last_run_time || "Never";

        if (data.status === "installed") {
          statusText.innerHTML = `<span style="color: var(--emerald); font-weight: 700;">● Installed (${data.state || 'Active'})</span>`;
          removeBtn.style.display = "inline-flex";
        } else {
          statusText.innerHTML = `<span style="color: var(--amber); font-weight: 700;">○ Not Installed</span>`;
          removeBtn.style.display = "none";
        }
      } catch (err) {
        console.error("Error loading schedule status:", err);
      }
    }

    async function saveSchedule(event) {
      event.preventDefault();
      const timeVal = document.getElementById("sched-time").value;
      const freqVal = document.getElementById("sched-frequency").value;
      const notifyVal = document.getElementById("sched-notify").checked;
      const saveBtn = document.getElementById("btn-save-sched");

      saveBtn.disabled = true;
      saveBtn.innerText = "Installing...";

      try {
        const res = await fetch("/api/schedule", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            action: "install",
            time: timeVal,
            frequency: freqVal,
            notify: notifyVal
          })
        });
        const data = await res.json();
        if (data.status === "error") {
          showToast(`Install failed: ${data.message}`, "❌");
        } else {
          showToast(`Scheduled priming installed for ${timeVal}!`, "✔");
          await loadScheduleStatus();
        }
      } catch (err) {
        showToast("Error saving schedule: " + err.message, "❌");
      } finally {
        saveBtn.disabled = false;
        saveBtn.innerText = "Save & Install Task";
      }
    }

    async function removeScheduleTask() {
      if (!confirm("Are you sure you want to remove the scheduled morning priming task?")) return;
      const removeBtn = document.getElementById("btn-remove-sched");
      removeBtn.disabled = true;
      removeBtn.innerText = "Removing...";

      try {
        const res = await fetch("/api/schedule", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ action: "remove" })
        });
        const data = await res.json();
        showToast("Scheduled morning priming removed.", "✔");
        await loadScheduleStatus();
      } catch (err) {
        showToast("Error removing schedule: " + err.message, "❌");
      } finally {
        removeBtn.disabled = false;
        removeBtn.innerText = "Uninstall Task";
      }
    }

    // Historical Analytics & Burn-Down Logic
    const AGENT_COLORS = {
      antigravity: "#06b6d4",
      codex: "#10b981",
      personal: "#8b5cf6",
      work: "#f59e0b",
      work2: "#f43f5e",
      cursor: "#3b82f6",
      windsurf: "#14b8a6",
      copilot: "#a855f7",
      aider: "#ec4899"
    };

    function getAgentColor(agentId) {
      const clean = (agentId || "").toLowerCase().replace("claude-", "");
      return AGENT_COLORS[clean] || "#94a3b8";
    }

    let currentAnalyticsDays = 7;

    async function fetchAnalytics(days = currentAnalyticsDays) {
      try {
        const [anaRes, histRes] = await Promise.all([
          fetch(`/api/analytics?days=${days}`),
          fetch(`/api/history?hours=${days * 24}`)
        ]);
        if (!anaRes.ok || !histRes.ok) return;
        const analytics = await anaRes.json();
        const history = await histRes.json();

        renderAnalyticsSummary(analytics);
        renderBurndownChart(history);
        renderHourlyDistribution(analytics.hourly_activity, analytics.peak_hours);
      } catch (err) {
        console.error("Error fetching analytics:", err);
      }
    }

    function changeAnalyticsPeriod(days, btn) {
      currentAnalyticsDays = days;
      document.querySelectorAll('.period-btn').forEach(b => b.classList.remove('active'));
      if (btn) btn.classList.add('active');
      fetchAnalytics(days);
    }

    async function triggerBackfill(btn) {
      const orig = btn.innerText;
      btn.disabled = true;
      btn.innerText = "⏳ Importing...";
      try {
        const res = await fetch("/api/backfill", { method: "POST" });
        const data = await res.json();
        if (data.success) {
          btn.innerText = `✔ +${data.pokes_imported} pokes`;
          setTimeout(() => { btn.innerText = orig; btn.disabled = false; }, 3000);
          fetchAnalytics(currentAnalyticsDays);
        } else {
          btn.innerText = "✖ Failed";
          setTimeout(() => { btn.innerText = orig; btn.disabled = false; }, 3000);
        }
      } catch (e) {
        btn.innerText = "✖ Error";
        setTimeout(() => { btn.innerText = orig; btn.disabled = false; }, 3000);
      }
    }

    function renderAnalyticsSummary(data) {
      document.getElementById("ana-active-ratio").innerText = `${data.active_time_ratio}%`;
      document.getElementById("ana-peak-hours").innerText = data.peak_hours_str || "No activity yet";
      document.getElementById("ana-rec-time").innerText = `⚡ ${data.recommended_poke_time}`;
      document.getElementById("ana-rec-reason").innerText = data.recommendation_reason || "Aligned for workday priming";
      document.getElementById("ana-events").innerText = `${data.total_snapshots} snaps`;
      document.getElementById("ana-pokes").innerText = `${data.total_pokes} verified pokes`;
    }

    function renderBurndownChart(history) {
      const container = document.getElementById("chart-container");
      const legend = document.getElementById("chart-legend");
      legend.innerHTML = "";

      if (!history || history.length === 0) {
        container.innerHTML = `
          <div style="display: flex; flex-direction: column; align-items: center; justify-content: center; height: 180px; color: var(--text-muted); font-size: 0.85rem;">
            <div style="font-size: 1.5rem; margin-bottom: 0.5rem;">📈</div>
            <div>No historical quota records logged yet.</div>
            <div style="font-size: 0.75rem; margin-top: 0.25rem;">Snapshots are recorded automatically as status checks and auto-checker runs.</div>
          </div>
        `;
        return;
      }

      const byAgent = {};
      const agentNames = {};
      let minTs = Infinity;
      let maxTs = -Infinity;

      history.forEach(pt => {
        const aid = pt.agent_id;
        if (!byAgent[aid]) byAgent[aid] = [];
        byAgent[aid].push(pt);
        agentNames[aid] = pt.agent_name || aid;
        if (pt.timestamp < minTs) minTs = pt.timestamp;
        if (pt.timestamp > maxTs) maxTs = pt.timestamp;
      });

      if (minTs === maxTs) {
        minTs = maxTs - 3600;
      }

      Object.keys(byAgent).forEach(aid => {
        const color = getAgentColor(aid);
        const item = document.createElement("div");
        item.className = "legend-item";
        item.innerHTML = `<span class="legend-dot" style="background: ${color};"></span><span>${agentNames[aid]}</span>`;
        legend.appendChild(item);
      });

      const svgWidth = 860;
      const svgHeight = 220;
      const padLeft = 45;
      const padRight = 20;
      const padTop = 20;
      const padBottom = 30;
      const chartW = svgWidth - padLeft - padRight;
      const chartH = svgHeight - padTop - padBottom;

      const scaleX = (ts) => padLeft + ((ts - minTs) / (maxTs - minTs)) * chartW;
      const scaleY = (pct) => padTop + chartH - (pct / 100.0) * chartH;

      let svg = `<svg viewBox="0 0 ${svgWidth} ${svgHeight}" class="chart-svg" style="width: 100%; height: auto;">`;

      [0, 25, 50, 75, 100].forEach(level => {
        const y = scaleY(level);
        svg += `<line x1="${padLeft}" y1="${y}" x2="${svgWidth - padRight}" y2="${y}" stroke="currentColor" stroke-opacity="0.08" stroke-dasharray="3,3" />`;
        svg += `<text x="${padLeft - 8}" y="${y + 4}" fill="currentColor" opacity="0.4" font-size="10" font-family="'JetBrains Mono', monospace" text-anchor="end">${level}%</text>`;
      });

      const startStr = new Date(minTs * 1000).toLocaleDateString([], { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' });
      const endStr = new Date(maxTs * 1000).toLocaleDateString([], { month: 'numeric', day: 'numeric', hour: '2-digit', minute: '2-digit' });
      svg += `<text x="${padLeft}" y="${svgHeight - 8}" fill="currentColor" opacity="0.4" font-size="10" font-family="'JetBrains Mono', monospace">${startStr}</text>`;
      svg += `<text x="${svgWidth - padRight}" y="${svgHeight - 8}" fill="currentColor" opacity="0.4" font-size="10" font-family="'JetBrains Mono', monospace" text-anchor="end">${endStr}</text>`;

      Object.entries(byAgent).forEach(([aid, pts]) => {
        const color = getAgentColor(aid);
        const polyPoints = pts.map(p => `${scaleX(p.timestamp).toFixed(1)},${scaleY(p.used_percent).toFixed(1)}`).join(" ");

        svg += `<polyline points="${polyPoints}" fill="none" stroke="${color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" opacity="0.85" />`;

        pts.forEach(p => {
          const cx = scaleX(p.timestamp).toFixed(1);
          const cy = scaleY(p.used_percent).toFixed(1);
          const dStr = new Date(p.timestamp * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
          svg += `<circle cx="${cx}" cy="${cy}" r="3" fill="${color}">
            <title>${agentNames[aid]}: ${p.used_percent}% used at ${dStr} (${p.is_active ? 'Active' : 'Inactive'})</title>
          </circle>`;
        });
      });

      svg += `</svg>`;
      container.innerHTML = svg;
    }

    function renderHourlyDistribution(hourlyActivity, peakHours = []) {
      const container = document.getElementById("hourly-bars");
      container.innerHTML = "";

      if (!hourlyActivity) return;
      const peakSet = new Set(peakHours || []);
      const maxCount = Math.max(...Object.values(hourlyActivity), 1);

      for (let h = 0; h < 24; h++) {
        const count = hourlyActivity[h] || 0;
        const isPeak = peakSet.has(h);
        const col = document.createElement("div");
        col.className = "hourly-bar-col";
        col.title = `${String(h).padStart(2, '0')}:00 - ${count} events logged${isPeak ? ' (Peak Hour)' : ''}`;

        const heightPct = count > 0 ? Math.max(8, Math.round((count / maxCount) * 100)) : 4;
        const bar = document.createElement("div");
        bar.className = `hourly-bar ${isPeak ? 'peak' : ''}`;
        bar.style.height = `${heightPct}%`;
        if (count === 0) bar.style.opacity = "0.2";

        const label = document.createElement("div");
        label.className = "hourly-bar-label";
        label.innerText = h % 3 === 0 ? String(h).padStart(2, '0') : "";

        col.appendChild(bar);
        col.appendChild(label);
        container.appendChild(col);
      }
    }

    // Initial Load & EventSource Startup
    fetchData();
    connectSSE();
    fetchAnalytics();
    setInterval(tickTimers, 1000);
  </script>
</body>
</html>
"""


def generate_html_file(output_path: Path) -> Path:
    output_path.write_text(HTML_TEMPLATE, encoding="utf-8")
    return output_path


class DashboardHandler(BaseHTTPRequestHandler):
    def log_message(self, format: str, *args: Any) -> None:
        # Suppress noisy HTTP request logging in terminal
        pass

    def do_GET(self) -> None:
        if self.path in ("/", "/index.html"):
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(HTML_TEMPLATE.encode("utf-8"))
        elif self.path.startswith("/api/status"):
            force_refresh = "refresh=true" in self.path
            statuses = get_all_statuses()
            data = [s.to_dict() for s in statuses]
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps(data).encode("utf-8"))
        elif self.path.startswith("/api/history"):
            parsed = urlparse(self.path)
            qs = parse_qs(parsed.query)
            aid = qs.get("agent_id", [None])[0]
            try:
                hrs = int(qs.get("hours", ["168"])[0])
            except Exception:
                hrs = 168
            data = get_history_points(agent_id=aid, hours=hrs)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps(data).encode("utf-8"))
        elif self.path.startswith("/api/analytics"):
            parsed = urlparse(self.path)
            qs = parse_qs(parsed.query)
            try:
                days = int(qs.get("days", ["7"])[0])
            except Exception:
                days = 7
            data = get_analytics_summary(days=days)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps(data).encode("utf-8"))
        elif self.path == "/api/schedule":
            data = get_schedule_status()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps(data).encode("utf-8"))
        elif self.path.startswith("/api/backfill"):
            from agent_quota_tracker.history import backfill_history

            res = backfill_history()
            _update_event.set()

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps(res).encode("utf-8"))
        elif self.path == "/api/stream":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()

            try:
                while _server_running:
                    statuses = get_all_statuses()
                    data = [s.to_dict() for s in statuses]
                    payload = f"event: quota_update\ndata: {json.dumps(data)}\n\n"
                    self.wfile.write(payload.encode("utf-8"))
                    self.wfile.flush()

                    # Wait up to 5 seconds, or wake instantly when an action is performed
                    _update_event.wait(timeout=5.0)
                    _update_event.clear()
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
                return
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self) -> None:
        content_len = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_len).decode("utf-8") if content_len > 0 else "{}"
        try:
            payload = json.loads(body)
        except Exception:
            payload = {}

        if self.path == "/api/poke":
            target_agent = payload.get("agent_id")
            force = payload.get("force", False)
            results = poke_all(force=force, agent_id=target_agent)
            data = [r.to_dict() for r in results]

            _update_event.set()

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps({"status": "ok", "results": data}).encode("utf-8"))

        elif self.path == "/api/schedule":
            action = payload.get("action", "status")
            if action == "install":
                t_str = payload.get("time", "07:30")
                freq = payload.get("frequency", "daily")
                notify = payload.get("notify", True)
                res = install_schedule(time_str=t_str, notify=notify, frequency=freq)
            elif action == "remove":
                res = remove_schedule()
            else:
                res = get_schedule_status()

            _update_event.set()

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps(res).encode("utf-8"))

        elif self.path == "/api/backfill":
            from agent_quota_tracker.history import backfill_history

            res = backfill_history()
            _update_event.set()

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps(res).encode("utf-8"))
        else:
            self.send_response(404)
            self.end_headers()


def start_dashboard_server(port: int = 5050, open_browser: bool = True) -> None:
    global _server_running
    _server_running = True

    html_file = Path("dashboard.html")
    generate_html_file(html_file)

    server = ThreadingHTTPServer(("127.0.0.1", port), DashboardHandler)
    url = f"http://localhost:{port}"

    print(f"\n🚀 Agents Dashboard v2 running at {url}")
    print(f"📄 Static HTML report generated: {html_file.resolve()}")
    print("Press Ctrl+C to stop the dashboard server.\n")

    if open_browser:
        threading.Thread(target=lambda: (time.sleep(0.5), webbrowser.open(url)), daemon=True).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping dashboard server...")
    finally:
        _server_running = False
        _update_event.set()
        server.server_close()
