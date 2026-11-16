const CARD_VERSION = "1.0.0";

class HeatmapCard extends HTMLElement {
  static getConfigElement() {
    return document.createElement("heatmap-card-editor");
  }

  static getStubConfig(hass) {
    const image = Object.keys(hass.states).find((entity) =>
      entity.startsWith("image.")
    );

    return {
      entity: image ?? "",
      title: "",
    };
  }

  set hass(hass) {
    this._hass = hass;

    if (!this._config) return;

    const state = hass.states[this._config.entity];

    if (!state) {
      this._renderError(`Unknown entity: ${this._config.entity}`);
      return;
    }

    if (this._lastState !== state.state) {
      this._lastState = state.state;
      this._render();
    }
  }

  setConfig(config) {
    if (!config?.entity) {
      throw new Error("You need to define an image entity (image.*).");
    }

    if (!config.entity.startsWith("image.")) {
      throw new Error("Entity must be an image entity.");
    }

    this._config = config;
    this._lastState = null;

    if (this._hass) {
      this.hass = this._hass;
    }
  }

  getCardSize() {
    return 5;
  }

  getGridOptions() {
    return {
      rows: 5,
      columns: 12,
      min_rows: 3,
    };
  }

  _renderError(message) {
    if (!this.shadowRoot) {
      this.attachShadow({ mode: "open" });
    }

    this.shadowRoot.innerHTML = `
      <ha-card>
        <div style="
          padding: 16px;
          color: var(--error-color);
        ">
          ${message}
        </div>
      </ha-card>
    `;
  }

  _render() {
    const state = this._hass.states[this._config.entity];

    const src = state?.attributes?.entity_picture ?? "";
    const title = this._config.title ?? "";
    const updated = state
      ? new Date(state.state).toLocaleString()
      : "";
    const attributes = state?.attributes ?? {};
    const width = Number(attributes.floorplan_width) || 0;
    const height = Number(attributes.floorplan_height) || 0;
    const radius = Number(attributes.marker_radius) || 0;
    const markers = attributes.show_markers && width && height
      ? (attributes.markers ?? [])
      : [];

    if (!this.shadowRoot) {
      this.attachShadow({ mode: "open" });
    }

    this.shadowRoot.innerHTML = `
      <style>
        ha-card {
          padding: 0;
          overflow: hidden;
        }

        .header {
          padding: 12px 16px 4px;
          font-weight: 500;
          font-size: 1.1em;
        }

        .wrap {
          position: relative;
          width: 100%;
        }

        .marker {
          position: absolute;
          padding: 0;
          border: 0;
          border-radius: 50%;
          background: transparent;
          cursor: pointer;
          transform: translate(-50%, -50%);
        }

        .marker:focus-visible {
          outline: 2px solid var(--primary-color);
          outline-offset: 2px;
        }

        img {
          display: block;
          width: 100%;
          height: auto;
        }

        .footer {
          padding: 6px 12px 10px;
          color: var(--secondary-text-color);
          font-size: 0.8em;
          text-align: right;
        }
      </style>

      <ha-card>
        ${
          title
            ? `<div class="header">${title}</div>`
            : ""
        }

        <div class="wrap">
          <img
            alt="Heatmap"
            src="${src}"
          />
          ${markers
            .map((marker) => {
              const x = Number(marker.x) || 0;
              const y = Number(marker.y) || 0;
              const entityId = this._escapeHtml(marker.entity_id);
              const label = this._escapeHtml(
                marker.label || marker.entity_id || "Sensor",
              );
              return `
                <button
                  class="marker"
                  type="button"
                  style="left: ${(x / width) * 100}%; top: ${(y / height) * 100}%; width: ${(radius * 2 / width) * 100}%; height: ${(radius * 2 / height) * 100}%;"
                  data-entity-id="${entityId}"
                  aria-label="Open ${label}"
                  title="${entityId}"
                ></button>
              `;
            })
            .join("")}
        </div>

        <div class="footer">
          Updated: ${updated}
        </div>
      </ha-card>
    `;

    for (const marker of this.shadowRoot.querySelectorAll(".marker")) {
      marker.addEventListener("click", () => {
        this.dispatchEvent(
          new CustomEvent("hass-more-info", {
            bubbles: true,
            composed: true,
            detail: { entityId: marker.dataset.entityId },
          }),
        );
      });
    }
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

customElements.define("heatmap-card", HeatmapCard);

window.customCards = window.customCards || [];

window.customCards.push({
  type: "heatmap-card",
  name: "Heatmap",
  preview: true,
  description: "Interpolated thermal heatmap overlay on a floorplan",
  documentationURL:
    "https://github.com/catcraft/HeatmappD#lovelace-card",
});