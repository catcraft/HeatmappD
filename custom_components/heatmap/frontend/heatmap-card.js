const CARD_VERSION = "1.0.3";

// Filled by the editor; see heatmap-card-editor.js.
const PENDING_LAYOUTS = (window.__heatmapPendingLayouts ??= new Map());

// Elements that only show a preview of a card that is not saved yet.
const PREVIEW_HOSTS = new Set([
  "HUI-DIALOG-EDIT-CARD",
  "HUI-CARD-PREVIEW",
  "HUI-CARD-PICKER",
  "HUI-DIALOG-CREATE-CARD",
]);

class HeatmapCard extends HTMLElement {
  /*
   * The editor is only loaded when a dashboard editor needs it. It is
   * imported with this file's query string; the integration derives that
   * string from both files, so a changed editor is never served from cache.
   */
  static async getConfigElement() {
    if (!customElements.get("heatmap-card-editor")) {
      const url = new URL("heatmap-card-editor.js", import.meta.url);
      url.search = new URL(import.meta.url).search;
      await import(url.href);
    }
    return document.createElement("heatmap-card-editor");
  }

  static getStubConfig(hass) {
    // Prefer an image entity created by this integration.
    const images = Object.keys(hass.states).filter((entity) =>
      entity.startsWith("image.")
    );
    const image =
      images.find((entity) =>
        Array.isArray(hass.states[entity].attributes?.markers)
      ) ?? images[0];

    return {
      entity: image ?? "",
      title: "",
    };
  }

  connectedCallback() {
    this._applyPendingLayout();
  }

  /*
   * The editor keeps dragged marker positions in PENDING_LAYOUTS and writes
   * their token into the card config. Once the dashboard's Save button stores
   * that config, the real (non-preview) card sends the layout to the
   * integration. On Cancel the token never reaches a saved card, so nothing
   * is applied.
   */
  _applyPendingLayout() {
    const revision = this._config?.layout_revision;

    if (
      !revision ||
      !this._hass ||
      !this.isConnected ||
      !PENDING_LAYOUTS.has(revision) ||
      this._isPreview()
    ) {
      return;
    }

    const pending = PENDING_LAYOUTS.get(revision);
    PENDING_LAYOUTS.delete(revision);

    this._hass
      .callWS({
        type: "heatmap/set_sensors",
        entry_id: pending.entryId,
        sensors: pending.sensors,
      })
      .catch((error) => {
        console.error("Failed to save Heatmap layout:", error);
        this.dispatchEvent(
          new CustomEvent("hass-notification", {
            bubbles: true,
            composed: true,
            detail: {
              message: `Heatmap layout could not be saved: ${
                error?.message || String(error)
              }`,
            },
          }),
        );
      });
  }

  /*
   * Only the card shown inside the edit/create dialogs counts as a preview.
   * The `preview` property is not used: Home Assistant also sets it on every
   * dashboard card while the dashboard is in edit mode, which would delay
   * the saved layout until edit mode is left.
   */
  _isPreview() {
    let node = this;

    while (node) {
      if (PREVIEW_HOSTS.has(node.tagName)) {
        return true;
      }

      node = node.parentNode || node.host;
    }

    return false;
  }

  set hass(hass) {
    this._hass = hass;
    this._applyPendingLayout();

    if (!this._config) return;

    const state = hass.states[this._config.entity];

    if (!state) {
      this._renderError(`Unknown entity: ${this._config.entity}`);
      return;
    }

    /*
     * Home Assistant replaces the state object whenever the state or an
     * attribute changes. That covers a new render, changed markers and the
     * rotating access token in entity_picture, so the image URL never goes
     * stale.
     */
    if (this._lastState !== state) {
      this._lastState = state;
      this._update(state);
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
    this._applyPendingLayout();

    if (this._hass) {
      this.hass = this._hass;
    }
  }

  // Width / height of the floorplan, or null while it is unknown.
  _aspectRatio() {
    const attributes =
      this._lastState?.attributes ??
      this._hass?.states[this._config?.entity]?.attributes;
    const width = Number(attributes?.floorplan_width) || 0;
    const height = Number(attributes?.floorplan_height) || 0;
    return width && height ? width / height : null;
  }

  // Masonry view: one unit is about 50 px, a column about 400 px wide.
  getCardSize() {
    const ratio = this._aspectRatio();
    return ratio ? Math.max(2, Math.round(400 / ratio / 50) + 1) : 5;
  }

  /*
   * Sections view: the height follows the floorplan's aspect ratio. If the
   * user sets a fixed number of rows, the image is fitted into them (see
   * the fixed-height styles).
   */
  getGridOptions() {
    return {
      columns: 12,
      rows: "auto",
      min_columns: 4,
    };
  }

  _renderError(message) {
    if (!this.shadowRoot) {
      this.attachShadow({ mode: "open" });
    }

    this._els = null;
    this._markersKey = null;
    this.shadowRoot.innerHTML = `
      <ha-card>
        <div style="
          padding: 16px;
          color: var(--error-color);
        ">
          ${this._escapeHtml(message)}
        </div>
      </ha-card>
    `;
  }

  /*
   * The elements are created once and then only updated. Replacing the
   * whole card on every state change recreated the <img>, which blanked
   * the image until the new one had loaded.
   */
  _ensureDom() {
    if (this._els) {
      return this._els;
    }

    if (!this.shadowRoot) {
      this.attachShadow({ mode: "open" });
    }

    this.shadowRoot.innerHTML = `
      <style>
        :host {
          display: block;
          height: 100%;
        }

        ha-card {
          display: flex;
          flex-direction: column;
          padding: 0;
          overflow: hidden;
        }

        ha-card.fixed-height {
          height: 100%;
        }

        .header {
          flex: none;
          padding: 12px 16px 4px;
          font-weight: 500;
          font-size: 1.1em;
        }

        .header[hidden] {
          display: none;
        }

        .body {
          position: relative;
        }

        /* Fit the floorplan into the rows the user chose, keeping its shape. */
        .fixed-height .body {
          flex: 1 1 auto;
          min-height: 0;
          container-type: size;
          display: flex;
          align-items: center;
          justify-content: center;
        }

        .wrap {
          position: relative;
          width: 100%;
          aspect-ratio: var(--ratio, auto);
        }

        .fixed-height .wrap {
          width: min(100cqw, 100cqh * var(--ratio-num, 1));
        }

        img {
          display: block;
          width: 100%;
          height: 100%;
        }

        .markers {
          position: absolute;
          inset: 0;
          pointer-events: none;
        }

        .marker {
          position: absolute;
          padding: 0;
          border: 0;
          border-radius: 50%;
          background: transparent;
          cursor: pointer;
          pointer-events: auto;
          transform: translate(-50%, -50%);
        }

        .marker:focus-visible {
          outline: 2px solid var(--primary-color);
          outline-offset: 2px;
        }

        .footer {
          flex: none;
          padding: 6px 12px 10px;
          color: var(--secondary-text-color);
          font-size: 0.8em;
          text-align: right;
        }
      </style>

      <ha-card>
        <div class="header" hidden></div>
        <div class="body">
          <div class="wrap">
            <img alt="Heatmap" />
            <div class="markers"></div>
          </div>
        </div>
        <div class="footer"></div>
      </ha-card>
    `;

    const root = this.shadowRoot;
    this._els = {
      card: root.querySelector("ha-card"),
      header: root.querySelector(".header"),
      wrap: root.querySelector(".wrap"),
      img: root.querySelector("img"),
      markers: root.querySelector(".markers"),
      footer: root.querySelector(".footer"),
    };
    this._markersKey = null;

    this._els.markers.addEventListener("click", (event) => {
      const marker = event.target.closest(".marker");

      if (!marker) {
        return;
      }

      this.dispatchEvent(
        new CustomEvent("hass-more-info", {
          bubbles: true,
          composed: true,
          detail: { entityId: marker.dataset.entityId },
        }),
      );
    });

    return this._els;
  }

  _update(state) {
    const els = this._ensureDom();
    const attributes = state.attributes ?? {};

    els.card.classList.toggle(
      "fixed-height",
      typeof this._config.grid_options?.rows === "number",
    );

    const title = this._config.title ?? "";
    els.header.textContent = title;
    els.header.hidden = !title;

    const width = Number(attributes.floorplan_width) || 0;
    const height = Number(attributes.floorplan_height) || 0;

    if (width && height) {
      els.wrap.style.setProperty("--ratio", `${width} / ${height}`);
      els.wrap.style.setProperty("--ratio-num", String(width / height));
    } else {
      els.wrap.style.removeProperty("--ratio");
      els.wrap.style.removeProperty("--ratio-num");
    }

    /*
     * entity_picture only changes when its access token rotates, not when a
     * new image is rendered, so the browser would keep showing its cached
     * copy. The state is the time of the last render; adding it to the URL
     * makes every new render a new URL. The old image stays visible until
     * the browser has loaded the new one.
     */
    const picture = attributes.entity_picture ?? "";
    const src = picture
      ? `${picture}${picture.includes("?") ? "&" : "?"}_=${encodeURIComponent(state.state)}`
      : "";
    if (els.img.getAttribute("src") !== src) {
      els.img.setAttribute("src", src);
    }

    const updatedDate = new Date(state.state);
    els.footer.textContent = `Updated: ${
      Number.isNaN(updatedDate.getTime()) ? "—" : updatedDate.toLocaleString()
    }`;

    this._updateMarkers(attributes, width, height);
  }

  _updateMarkers(attributes, width, height) {
    const radius = Number(attributes.marker_radius) || 0;
    const markers = attributes.show_markers && width && height
      ? (attributes.markers ?? [])
      : [];

    // Only rebuild the buttons when the layout changed, not on every render.
    const key = JSON.stringify([markers, radius, width, height]);
    if (key === this._markersKey) {
      return;
    }
    this._markersKey = key;

    this._els.markers.innerHTML = markers
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
      .join("");
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

if (!customElements.get("heatmap-card")) {
  customElements.define("heatmap-card", HeatmapCard);
}

window.customCards = window.customCards || [];

if (!window.customCards.some((card) => card.type === "heatmap-card")) {
  window.customCards.push({
    type: "heatmap-card",
    name: "Heatmap",
    preview: true,
    description: "Interpolated thermal heatmap overlay on a floorplan",
    documentationURL:
      "https://github.com/catcraft/HeatmappD#dashboard-card",
  });
}