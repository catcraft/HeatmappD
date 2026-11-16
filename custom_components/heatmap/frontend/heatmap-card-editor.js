const EDITOR_VERSION = "1.0.2";

class HeatmapCardEditor extends HTMLElement {
  connectedCallback() {
    if (!this._rendered) {
      this._render();
    }
  }

  set hass(hass) {
    this._hass = hass;

    if (!this._rendered) {
      this._render();
    }
  }

  setConfig(config) {
    this._config = config || {};
    this._render();
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

    try {
      const entries = await this._fetchEntries();

      const imageEntities = Object.keys(this._hass.states)
        .filter((entityId) => entityId.startsWith("image."))
        .sort();

      const selectedEntity =
        this._config?.entity || imageEntities[0] || "";

      /*
       * Home Assistant does not always expose config_entry_id through
       * hass.entities. First try normal registry matching.
       */
      const registryItem = Object.values(
        this._hass.entities || {},
      ).find((entity) => entity.entity_id === selectedEntity);

      let entryId = registryItem?.config_entry_id || null;

      /*
       * If only one Heatmap integration entry exists, use it automatically.
       */
      if (!entryId && entries.length === 1) {
        entryId = entries[0].entry_id;
      }

      /*
       * Fallback for multiple Heatmap entries:
       * match the selected image entity with the integration entry title.
       */
      if (!entryId && entries.length > 1 && selectedEntity) {
        const entityObjectId = selectedEntity
          .replace(/^image\./, "")
          .toLowerCase();

        const normalizedEntityName = entityObjectId
          .replaceAll("_", " ")
          .trim();

        const matchingEntry = entries.find((entry) => {
          const title = String(entry.title || "")
            .toLowerCase()
            .trim();

          const normalizedTitleObjectId = title.replaceAll(" ", "_");

          return (
            title === normalizedEntityName ||
            normalizedTitleObjectId === entityObjectId
          );
        });

        entryId = matchingEntry?.entry_id || null;
      }

      const currentEntry = entryId
        ? await this._fetchEntry(entryId)
        : null;

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
                    No image entities found
                  </option>
                `
            }
          </select>
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
            ? this._placer(currentEntry, selectedEntity)
            : `
              <p class="error">
                No matching Heatmap entry was found.
                Found ${entries.length} Heatmap integration entries.
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
      console.error("Failed to render Heatmap editor:", error);

      this.shadowRoot.innerHTML = `
        <p style="color: var(--error-color);">
          Failed to load the Heatmap placement editor:
          ${this._escapeHtml(error?.message || String(error))}
        </p>
      `;
    }
  }

  _placer(entry, selectedEntity) {
    const sensors = entry.options?.sensors || [];
    const width = Number(entry.floorplan?.width || 0);
    const height = Number(entry.floorplan?.height || 0);

    const entityPicture =
      this._hass.states[selectedEntity]?.attributes?.entity_picture || "";

    if (!width || !height) {
      return `
        <p class="error">
          The floorplan dimensions are missing. Replace the floorplan in the
          Heatmap integration options.
        </p>
      `;
    }

    if (!entityPicture) {
      return `
        <p class="error">
          The selected image entity does not provide an entity_picture
          attribute.
        </p>
      `;
    }

    /*
     * Convert Home Assistant's relative entity_picture URL into a complete URL.
     * This also keeps the access token contained in the entity_picture URL.
     */
    const imageUrl =
      typeof this._hass.hassUrl === "function"
        ? this._hass.hassUrl(entityPicture)
        : entityPicture;

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
            src="${this._escapeHtml(imageUrl)}"
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
        <button
          id="save"
          type="button"
          ${sensors.length === 0 ? "disabled" : ""}
        >
          Save layout
        </button>

        <button id="reload" type="button">
          Reload
        </button>

        <span id="status" class="status"></span>
      </div>
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
      entry.options?.sensors || [],
    );

    const status = this.shadowRoot.getElementById("status");
    const image = this.shadowRoot.getElementById("floorplan-image");

    let draggingMarker = null;
    let draggingPointerId = null;

    const stopDragging = () => {
      if (draggingMarker) {
        draggingMarker.classList.remove("dragging");
      }

      draggingMarker = null;
      draggingPointerId = null;
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
      .getElementById("save")
      ?.addEventListener("click", async (event) => {
        const saveButton = event.currentTarget;

        if (status) {
          status.classList.remove("error");
          status.textContent = "Saving...";
        }

        saveButton.disabled = true;

        try {
          await this._saveSensors(entry.entry_id, sensors);

          if (status) {
            status.classList.remove("error");
            status.textContent = "Layout saved.";
          }
        } catch (error) {
          console.error(
            "Failed to save sensor positions:",
            error,
          );

          if (status) {
            status.textContent =
              `Save failed: ${error?.message || String(error)}`;

            status.classList.add("error");
          }
        } finally {
          saveButton.disabled = sensors.length === 0;
        }
      });

    this.shadowRoot
      .getElementById("reload")
      ?.addEventListener("click", () => {
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