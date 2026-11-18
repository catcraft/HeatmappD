const EDITOR_VERSION = "1.0.3";
const AUTO_SAVE_DELAY_MS = 1000;

/*
 * Layouts waiting for the dashboard's Save button, keyed by the
 * layout_revision token written into the card config. Shared with the card,
 * which sends the layout to the integration once the config is saved.
 */
const PENDING_LAYOUTS = (window.__heatmapPendingLayouts ??= new Map());

function newLayoutRevision() {
  return (
    Date.now().toString(36) + Math.random().toString(36).slice(2, 10)
  );
}

class HeatmapCardEditor extends HTMLElement {
  connectedCallback() {
    if (!this._rendered && !this._renderPending) {
      this._render();
    }
  }

  set hass(hass) {
    this._hass = hass;

    // hass is set on every state change; start at most one first render.
    if (!this._rendered && !this._renderPending) {
      this._render();
    }
  }

  setConfig(config) {
    const previousEntity = this._config?.entity;
    this._config = config || {};

    if (this._initialRevision === undefined) {
      this._initialRevision = this._config.layout_revision ?? null;
    }

    /*
     * Home Assistant calls setConfig again after every config-changed event.
     * Re-rendering then would reload positions from the server and throw
     * away the markers the user just dragged, so only re-render when the
     * selected entity changes.
     */
    if (!this._rendered || previousEntity !== this._config.entity) {
      this._render();
    } else {
      this._syncControls();
    }
  }

  _syncControls() {
    const autoSave = this.shadowRoot?.getElementById("auto-save");

    if (autoSave) {
      autoSave.checked = Boolean(this._config?.auto_save);
    }

    this._updateHint();
  }

  _hintText() {
    return this._config?.auto_save
      ? "Marker positions are saved automatically."
      : "Marker positions are applied when you press Save.";
  }

  _updateHint() {
    const hint = this.shadowRoot?.getElementById("save-hint");

    if (hint) {
      hint.textContent = this._hintText();
    }
  }

  _pendingFor(entryId) {
    const pending = PENDING_LAYOUTS.get(this._config?.layout_revision);
    return pending && pending.entryId === entryId ? pending : null;
  }

  _configWithoutPending() {
    const config = { ...this._config };

    if (this._initialRevision === null) {
      delete config.layout_revision;
    } else {
      config.layout_revision = this._initialRevision;
    }

    return config;
  }

  async _fetchEntries() {
    return this._hass.callWS({
      type: "heatmap/list_entries",
    });
  }

  async _fetchEntry(entryId) {
    return this._hass.callWS({
      type: "heatmap/get_entry",
      entry_id: entryId,
    });
  }

  /*
   * The heatmap without markers: the image entity has the saved markers
   * drawn in, which would show the old positions under the dragged ones.
   */
  async _fetchPreview(entryId) {
    const result = await this._hass.callWS({
      type: "heatmap/render_preview",
      entry_id: entryId,
    });
    return `data:${result.content_type};base64,${result.data}`;
  }

  async _saveSensors(entryId, sensors) {
    return this._hass.callWS({
      type: "heatmap/set_sensors",
      entry_id: entryId,
      sensors,
    });
  }

  _configChanged(newConfig) {
    this._config = newConfig;

    this.dispatchEvent(
      new CustomEvent("config-changed", {
        detail: {
          config: newConfig,
        },
        bubbles: true,
        composed: true,
      }),
    );
  }

  async _render() {
    if (!this._hass) {
      return;
    }

    if (!this.shadowRoot) {
      this.attachShadow({ mode: "open" });
    }

    /*
     * Renders can overlap (setConfig with a new entity while the first render
     * still waits for the server). Only the newest one may touch the DOM.
     */
    const token = (this._renderToken = (this._renderToken ?? 0) + 1);
    const isCurrent = () => token === this._renderToken;
    this._renderPending = true;

    try {
      const entries = await this._fetchEntries();

      // Each entry lists its own image entities (from the entity registry).
      const entryByEntity = new Map();
      for (const entry of entries) {
        for (const entityId of entry.entity_ids ?? []) {
          entryByEntity.set(entityId, entry);
        }
      }

      const imageEntities = [...entryByEntity.keys()].sort();
      const configured = this._config?.entity || "";

      // Keep a configured entity in the list even if it is not a heatmap,
      // so the select shows what the card really uses.
      if (configured && !entryByEntity.has(configured)) {
        imageEntities.unshift(configured);
      }

      const selectedEntity = configured || imageEntities[0] || "";
      const entryId = entryByEntity.get(selectedEntity)?.entry_id ?? null;

      let currentEntry = null;
      let previewUrl = null;
      let previewError = null;

      if (entryId) {
        [currentEntry, previewUrl] = await Promise.all([
          this._fetchEntry(entryId),
          this._fetchPreview(entryId).catch((error) => {
            console.error("Failed to render Heatmap preview:", error);
            previewError = error?.message || String(error);
            return null;
          }),
        ]);
      }

      if (!isCurrent()) {
        return;
      }

      this.shadowRoot.innerHTML = `
        <style>
          :host {
            display: block;
          }

          a {
            text-decoration: none;
            color: #464feb;
          }

          tr th,
          tr td {
            border: 1px solid #e6e6e6;
          }

          tr th {
            background-color: #f5f5f5;
          }

          .row {
            display: flex;
            gap: 8px;
            align-items: center;
            margin: 8px 0;
          }

          label {
            min-width: 130px;
          }

          input.checkbox {
            flex: 0 0 auto;
            width: 18px;
            height: 18px;
          }

          select,
          input {
            flex: 1;
            min-width: 0;
            padding: 6px;
            box-sizing: border-box;
          }

          .placement-header {
            margin-top: 16px;
          }

          .placer-wrapper {
            width: 100%;
            margin: 12px 0;
          }

          .placer {
            position: relative;
            display: block;
            width: 100%;
            overflow: hidden;
            border-radius: 6px;
            user-select: none;
            background: var(--secondary-background-color);
          }

          .placer img {
            display: block;
            width: 100%;
            height: auto;
            pointer-events: none;
            user-select: none;
          }

          .marker {
            position: absolute;
            width: 20px;
            height: 20px;
            border-radius: 50%;
            background: white;
            border: 3px solid black;
            transform: translate(-50%, -50%);
            cursor: grab;
            touch-action: none;
            box-sizing: border-box;
            z-index: 2;
          }

          .marker:hover {
            box-shadow: 0 0 0 3px
              color-mix(
                in srgb,
                var(--primary-color) 40%,
                transparent
              );
          }

          .marker.dragging {
            cursor: grabbing;
            box-shadow: 0 0 0 3px var(--primary-color);
            z-index: 3;
          }

          .lbl {
            position: absolute;
            left: 22px;
            top: -6px;
            white-space: nowrap;
            color: black;
            background: rgba(255, 255, 255, 0.9);
            padding: 2px 5px;
            border-radius: 3px;
            font-size: 12px;
            line-height: 16px;
            pointer-events: none;
            box-shadow: 0 1px 3px rgba(0, 0, 0, 0.25);
          }

          .actions {
            display: flex;
            align-items: center;
            flex-wrap: wrap;
            gap: 8px;
            margin-top: 12px;
          }

          button {
            padding: 6px 12px;
            cursor: pointer;
          }

          button:disabled {
            cursor: default;
            opacity: 0.6;
          }

          .status {
            color: var(--secondary-text-color);
          }

          .error {
            color: var(--error-color);
          }
        </style>

        <div class="row">
          <label for="entity">Image entity</label>

          <select id="entity">
            ${
              imageEntities.length > 0
                ? imageEntities
                    .map(
                      (entityId) => `
                        <option
                          value="${this._escapeHtml(entityId)}"
                          ${
                            entityId === selectedEntity
                              ? "selected"
                              : ""
                          }
                        >
                          ${this._escapeHtml(entityId)}
                        </option>
                      `,
                    )
                    .join("")
                : `
                  <option value="">
                    No Heatmap image entities found
                  </option>
                `
            }
          </select>
        </div>

        <div class="row">
          <label for="auto-save">Auto-save layout</label>

          <input
            id="auto-save"
            class="checkbox"
            type="checkbox"
            ${this._config?.auto_save ? "checked" : ""}
          >
        </div>

        <div class="row">
          <label for="title">Card title</label>

          <input
            id="title"
            type="text"
            value="${this._escapeHtml(this._config?.title || "")}"
          >
        </div>

        ${
          currentEntry
            ? this._placer(currentEntry, previewUrl, previewError)
            : `
              <p class="error">
                ${
                  selectedEntity
                    ? `${this._escapeHtml(selectedEntity)} does not belong to a
                      loaded Heatmap integration entry.`
                    : "Add the Heatmap integration first."
                }
              </p>
            `
        }
      `;

      this.shadowRoot
        .getElementById("entity")
        ?.addEventListener("change", (event) => {
          this._configChanged({
            ...this._config,
            entity: event.target.value,
          });
        });

      this.shadowRoot
        .getElementById("title")
        ?.addEventListener("input", (event) => {
          this._configChanged({
            ...this._config,
            title: event.target.value,
          });
        });

      if (currentEntry) {
        this._wire(currentEntry);
      }

      this._rendered = true;
    } catch (error) {
      if (!isCurrent()) {
        return;
      }

      console.error("Failed to render Heatmap editor:", error);

      this.shadowRoot.innerHTML = `
        <p style="color: var(--error-color);">
          Failed to load the Heatmap placement editor:
          ${this._escapeHtml(error?.message || String(error))}
        </p>
      `;
      // Do not retry on every state change; reopening the editor retries.
      this._rendered = true;
    } finally {
      if (isCurrent()) {
        this._renderPending = false;
      }
    }
  }

  _placer(entry, previewUrl, previewError) {
    const sensors =
      this._pendingFor(entry.entry_id)?.sensors ||
      entry.options?.sensors ||
      [];
    const width = Number(entry.floorplan?.width || 0);
    const height = Number(entry.floorplan?.height || 0);

    if (!width || !height) {
      return `
        <p class="error">
          The floorplan dimensions are missing. Replace the floorplan in the
          Heatmap integration options.
        </p>
      `;
    }

    if (!previewUrl) {
      return `
        <p class="error">
          The floorplan preview could not be rendered${
            previewError ? `: ${this._escapeHtml(previewError)}` : "."
          }
        </p>
      `;
    }

    return `
      <div class="placement-header">
        <strong>
          Sensor placement -
          ${this._escapeHtml(entry.title || "Heatmap")}
        </strong>
      </div>

      <p>
        Floorplan: ${width} × ${height} px.
        Drag the white markers to position the sensors.
      </p>

      <div class="placer-wrapper">
        <div
          class="placer"
          id="placer"
          data-entry="${this._escapeHtml(entry.entry_id)}"
          data-w="${width}"
          data-h="${height}"
        >
          <img
            id="floorplan-image"
            src="${this._escapeHtml(previewUrl)}"
            alt="${this._escapeHtml(
              entry.title || "Heatmap floorplan",
            )}"
            draggable="false"
          >

          ${sensors
            .map((sensor, index) => {
              const x = Number(sensor.x || 0);
              const y = Number(sensor.y || 0);

              const left = Math.max(
                0,
                Math.min(100, (x / width) * 100),
              );

              const top = Math.max(
                0,
                Math.min(100, (y / height) * 100),
              );

              const label =
                sensor.label ||
                sensor.name ||
                sensor.entity_id ||
                `Sensor ${index + 1}`;

              return `
                <div
                  class="marker"
                  data-index="${index}"
                  style="left: ${left}%; top: ${top}%;"
                  title="${this._escapeHtml(
                    sensor.entity_id || label,
                  )}"
                >
                  <span class="lbl">
                    ${this._escapeHtml(label)}
                  </span>
                </div>
              `;
            })
            .join("")}
        </div>
      </div>

      ${
        sensors.length === 0
          ? `
            <p class="error">
              No sensors are configured. Add sensors in the Heatmap
              integration options first.
            </p>
          `
          : ""
      }

      <div class="actions">
        <button id="reload" type="button">
          Discard changes
        </button>

        <span id="status" class="status"></span>
      </div>

      <p id="save-hint" class="status">${this._hintText()}</p>
    `;
  }

  _wire(entry) {
    const placer = this.shadowRoot.getElementById("placer");

    if (!placer) {
      return;
    }

    const width = Number(placer.dataset.w);
    const height = Number(placer.dataset.h);

    const sensors = structuredClone(
      this._pendingFor(entry.entry_id)?.sensors ||
        entry.options?.sensors ||
        [],
    );

    const status = this.shadowRoot.getElementById("status");
    const image = this.shadowRoot.getElementById("floorplan-image");

    let draggingMarker = null;
    let draggingPointerId = null;
    let moved = false;

    const setStatus = (text, isError = false) => {
      if (!status) {
        return;
      }

      status.textContent = text;
      status.classList.toggle("error", isError);
    };

    const saveNow = async (layout) => {
      setStatus("Saving...");

      try {
        await this._saveSensors(entry.entry_id, layout);
        setStatus("Layout saved.");
      } catch (error) {
        console.error("Failed to save sensor positions:", error);
        setStatus(`Save failed: ${error?.message || String(error)}`, true);
      }
    };

    const layoutChanged = () => {
      if (this._config?.auto_save) {
        clearTimeout(this._autoSaveTimer);
        setStatus("Unsaved changes...");
        const layout = structuredClone(sensors);
        this._autoSaveTimer = setTimeout(
          () => saveNow(layout),
          AUTO_SAVE_DELAY_MS,
        );
        return;
      }

      /*
       * Reuse only a token this editor session created. A token from an
       * earlier session may still be waiting in PENDING_LAYOUTS; reusing it
       * would leave the config unchanged and the dialog's Save button grey.
       */
      let revision = this._sessionRevision;

      if (!revision || this._config?.layout_revision !== revision) {
        revision = newLayoutRevision();
        this._sessionRevision = revision;

        // Drop older unsaved layouts of this heatmap so they never apply later.
        for (const [key, value] of PENDING_LAYOUTS) {
          if (value.entryId === entry.entry_id) {
            PENDING_LAYOUTS.delete(key);
          }
        }
      }

      PENDING_LAYOUTS.set(revision, {
        entryId: entry.entry_id,
        sensors: structuredClone(sensors),
      });

      if (this._config?.layout_revision !== revision) {
        // Changing the config enables the dialog's Save button.
        this._configChanged({ ...this._config, layout_revision: revision });
      }

      setStatus("Unsaved layout changes.");
    };

    const stopDragging = () => {
      if (!draggingMarker) {
        return;
      }

      draggingMarker.classList.remove("dragging");
      draggingMarker = null;
      draggingPointerId = null;

      if (moved) {
        moved = false;
        layoutChanged();
      }
    };

    for (const marker of placer.querySelectorAll(".marker")) {
      marker.addEventListener("pointerdown", (event) => {
        draggingMarker = marker;
        draggingPointerId = event.pointerId;

        marker.classList.add("dragging");
        marker.setPointerCapture(event.pointerId);

        event.preventDefault();
        event.stopPropagation();
      });

      marker.addEventListener("pointerup", (event) => {
        if (
          draggingPointerId !== null &&
          marker.hasPointerCapture(event.pointerId)
        ) {
          marker.releasePointerCapture(event.pointerId);
        }

        stopDragging();
      });

      marker.addEventListener("pointercancel", stopDragging);

      marker.addEventListener("lostpointercapture", stopDragging);
    }

    placer.addEventListener("pointermove", (event) => {
      if (!draggingMarker) {
        return;
      }

      const rect = placer.getBoundingClientRect();

      if (!rect.width || !rect.height) {
        return;
      }

      const displayX = Math.max(
        0,
        Math.min(rect.width, event.clientX - rect.left),
      );

      const displayY = Math.max(
        0,
        Math.min(rect.height, event.clientY - rect.top),
      );

      const sensorIndex = Number(
        draggingMarker.dataset.index,
      );

      if (!Number.isInteger(sensorIndex) || !sensors[sensorIndex]) {
        return;
      }

      const percentageX = (displayX / rect.width) * 100;
      const percentageY = (displayY / rect.height) * 100;

      draggingMarker.style.left = `${percentageX}%`;
      draggingMarker.style.top = `${percentageY}%`;

      sensors[sensorIndex].x = Math.round(
        (displayX / rect.width) * width,
      );

      sensors[sensorIndex].y = Math.round(
        (displayY / rect.height) * height,
      );

      moved = true;

      if (status) {
        status.classList.remove("error");
        status.textContent =
          `x: ${sensors[sensorIndex].x}, ` +
          `y: ${sensors[sensorIndex].y}`;
      }

      event.preventDefault();
    });

    image?.addEventListener("error", () => {
      console.error(
        "Failed to load Heatmap floorplan image:",
        image.src,
      );

      if (status) {
        status.textContent = "Failed to load the floorplan image.";
        status.classList.add("error");
      }
    });

    this.shadowRoot
      .getElementById("auto-save")
      ?.addEventListener("change", (event) => {
        const config = { ...this._config, auto_save: event.target.checked };
        const pending = this._pendingFor(entry.entry_id);

        /*
         * Turning auto-save on while changes are pending saves them now, so
         * they do not wait for a Save that would no longer apply them.
         */
        if (event.target.checked && pending) {
          PENDING_LAYOUTS.delete(this._config.layout_revision);
          this._config = config;
          this._configChanged(this._configWithoutPending());
          saveNow(pending.sensors);
        } else {
          this._configChanged(config);
        }

        this._updateHint();
      });

    this.shadowRoot
      .getElementById("reload")
      ?.addEventListener("click", () => {
        clearTimeout(this._autoSaveTimer);

        if (this._pendingFor(entry.entry_id)) {
          PENDING_LAYOUTS.delete(this._config.layout_revision);
          this._configChanged(this._configWithoutPending());
        }

        this._render();
      });
  }

  _escapeHtml(value) {
    return String(value ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }
}

if (!customElements.get("heatmap-card-editor")) {
  customElements.define(
    "heatmap-card-editor",
    HeatmapCardEditor,
  );
}

console.info(
  `%c HEATMAP-CARD-EDITOR %c ${EDITOR_VERSION} `,
  "color: white; background: #03a9f4; font-weight: bold;",
  "color: #03a9f4; background: white; font-weight: bold;",
);