// The card editor: pick the receiver and the main volume unit (Home Assistant's own form).

const FIELDS = [
  { name: "device_id", selector: { device: { integration: "onkyo_eiscp" } } },
  {
    name: "volume_unit",
    selector: {
      select: {
        mode: "dropdown",
        options: [
          { value: "db", label: "dB (the receiver's own units where it has no dB scale)" },
          { value: "percent", label: "Percent" },
        ],
      },
    },
  },
];
const LABELS = { device_id: "Receiver", volume_unit: "Main volume unit" };

class OnkyoRemoteCardEditor extends HTMLElement {
  setConfig(config) {
    this._config = config;
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    if (this._form) this._form.hass = hass;
  }

  _render() {
    if (!this._form) {
      this._form = document.createElement("ha-form");
      this._form.schema = FIELDS;
      this._form.computeLabel = (field) => LABELS[field.name] ?? field.name;
      this._form.addEventListener("value-changed", (event) => {
        event.stopPropagation();
        const config = { ...this._config, ...event.detail.value };
        for (const key of Object.keys(config)) if (config[key] === undefined || config[key] === "") delete config[key];
        this._config = config;
        this.dispatchEvent(new CustomEvent("config-changed", { detail: { config }, bubbles: true, composed: true }));
      });
      this.append(this._form);
    }
    this._form.hass = this._hass;
    this._form.data = { volume_unit: "db", ...this._config };
  }
}

if (!customElements.get("onkyo-remote-card-editor")) {
  customElements.define("onkyo-remote-card-editor", OnkyoRemoteCardEditor);
}
