// The look of the card, the rename sheet and the sidebar page (DESIGN.md tokens only:
// Home Assistant theme variables, hex values appear only as fallbacks).

export const STYLE = `
:host{display:block}
*{box-sizing:border-box}
/* ============ THE CARD ============ */
.oc{
  --r:var(--ha-card-border-radius,12px);--ir:calc(var(--r) - 3px);
  --ctl:color-mix(in srgb,var(--disabled-color,#bdbdbd) 22%,transparent);
  --hov:color-mix(in srgb,var(--primary-text-color,#212121) 10%,transparent);
  --prs:color-mix(in srgb,var(--primary-text-color,#212121) 18%,transparent);
  --sel:color-mix(in srgb,var(--primary-color,#009ac7) 20%,transparent);
  --bg:var(--ha-card-background,var(--card-background-color,#fff));
  --state:var(--secondary-text-color);--pane:604px;
  position:relative;container-type:inline-size;color:var(--primary-text-color,#212121);overflow:hidden;display:block;
  font-family:var(--ha-font-family-body,Roboto,system-ui,sans-serif);font-size:14px;line-height:1.4}
.oc.on{--state:var(--primary-color)}
:where(.oc,.dlg-root) :where(button){font:inherit;color:inherit;-webkit-tap-highlight-color:transparent}
.oc svg,.dlg-root svg{display:block;flex:none}
.in{padding:12px;display:flex;flex-direction:column;gap:12px}

/* busy shimmer (a listening mode change waits for the receiver) */
.busy{position:absolute;inset:0 0 auto 0;height:2px;overflow:hidden;opacity:0;transition:opacity .15s}
.busy::after{content:"";position:absolute;top:0;bottom:0;width:40%;left:-40%;
  background:linear-gradient(90deg,transparent,var(--primary-color),transparent);animation:shimmer 1s linear infinite}
.oc.sending .busy{opacity:1}
@keyframes shimmer{to{left:100%}}

/* header */
.head{display:flex;align-items:center;gap:12px;min-height:48px}
.hicon{width:40px;height:40px;border-radius:50%;display:grid;place-items:center;flex:none;
  color:var(--state);background:color-mix(in srgb,var(--state) 20%,transparent)}
.htxt{flex:1;min-width:0}
.hname{font-size:16px;font-weight:500;line-height:1.3;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.hsub{font-size:14px;color:var(--secondary-text-color);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.power{width:48px;height:48px;border-radius:var(--r);display:grid;place-items:center;flex:none;background-color:var(--ctl)}
.oc.on .power{background-color:var(--primary-color);color:var(--text-primary-color,#fff)}

/* pressable overlay */
.pr{cursor:pointer;border:0;transition:background-color .12s}
.pr:hover{background-image:linear-gradient(var(--hov),var(--hov))}
.pr:active,.pr.flash{background-image:linear-gradient(var(--prs),var(--prs))}
.pr:focus-visible{outline:2px solid var(--primary-color);outline-offset:2px}

/* segmented grids (ha-control-select style) */
.seg{display:grid;grid-template-columns:repeat(var(--cols,4),minmax(0,1fr));gap:4px;padding:4px;border-radius:var(--r);background:var(--ctl)}
.opt{min-height:40px;border-radius:var(--ir);background-color:transparent;padding:3px 6px;font-size:14px;line-height:1.15;text-align:center;
  display:flex;flex-direction:column;align-items:center;justify-content:center;overflow-wrap:anywhere;overflow:hidden;min-width:0;hyphens:manual;color:var(--primary-text-color)}
.opt .t{display:-webkit-box;-webkit-box-orient:vertical;-webkit-line-clamp:2;line-clamp:2;overflow:hidden;max-width:100%}
.opt small{font-size:11px;color:var(--secondary-text-color);line-height:1.15}
.opt.sel{background-color:var(--sel);box-shadow:inset 0 0 0 2px var(--primary-color);font-weight:500}
.opt.pend{box-shadow:inset 0 0 0 2px var(--primary-color);animation:pulse 1s ease-in-out infinite}
@keyframes pulse{50%{box-shadow:inset 0 0 0 2px transparent}}
.seg.dense .opt{min-height:40px;font-size:13px}
@container (max-width:340px){ .opt{font-size:13px;padding:3px 3px} .seg.dense .opt{font-size:12px} }

/* tabs */
.tabs{--cols:6}
.tabs .opt{gap:2px;min-height:50px;font-size:12px;padding:4px 2px}
.tabs .opt svg{width:20px;height:20px}

/* groups */
.pane{height:var(--pane);display:flex;flex-direction:column;gap:12px;min-height:0}
.pane .col{display:contents}
.pane.p-main{gap:var(--mgap,12px)}
.pane.p-main > .col:last-child > .grp:last-child{margin-top:auto}
.grp{border:1px solid var(--divider-color);border-radius:var(--r);padding:12px;display:flex;flex-direction:column;gap:10px;min-width:0}
.grp.tight{gap:8px}
.gh{display:flex;align-items:center;justify-content:space-between;gap:8px;min-height:22px}
.gt{font-size:14px;font-weight:500}
.gv{font-size:14px;color:var(--secondary-text-color);text-align:right;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.gv.num{font-variant-numeric:tabular-nums;color:var(--primary-text-color);font-weight:500}
.vread{display:inline-flex;align-items:center;gap:8px;min-height:40px;margin:-10px -8px -10px 0;padding:0 8px;border-radius:20px;background-color:transparent;
  font-variant-numeric:tabular-nums;font-weight:500;font-size:15px;color:var(--primary-text-color)}
.vread small{font-size:13px;font-weight:400;color:var(--secondary-text-color)}
.lbl{font-size:12px;color:var(--secondary-text-color);margin-bottom:-4px}
.tbtn{min-height:40px;padding:0 10px;border-radius:20px;background-color:transparent;color:var(--primary-color);font-weight:500;font-size:14px;
  display:inline-flex;align-items:center;gap:6px;margin:-10px -6px -10px 0}
.tbtn svg{width:18px;height:18px}
.qnote{display:flex;align-items:center;gap:8px;font-size:13px;color:var(--secondary-text-color);padding:0 4px;min-height:24px}
.qnote svg{width:18px;height:18px}
.notice{display:flex;align-items:center;gap:10px;padding:10px 12px;border-radius:var(--r);background:var(--ctl);font-size:14px}
.notice svg{color:var(--secondary-text-color)}
.ctl{transition:opacity .2s}
.oc:not(.on) .ctl{opacity:.35;pointer-events:none}

/* mode row on Main */
.mrow{display:flex;align-items:center;gap:12px;min-height:44px;width:100%;text-align:left;border-radius:var(--ir);padding:0 4px 0 0;background-color:transparent}
.mrow .n{flex:1;min-width:0}
.mrow .n b{display:block;font-weight:500;font-size:16px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.mrow .n small{display:block;font-size:12px;color:var(--secondary-text-color)}
.mrow svg{color:var(--secondary-text-color)}

/* keys and sliders */
.key{display:flex;flex-direction:column;align-items:center;justify-content:center;gap:2px;min-height:52px;min-width:44px;
  border-radius:var(--r);background-color:var(--ctl);color:var(--primary-color);padding:6px 4px}
.key span{font-size:12px;color:var(--secondary-text-color)}
.keys{display:grid;grid-template-columns:repeat(var(--n,3),minmax(0,1fr));gap:8px}
.ibtn{width:44px;height:44px;flex:none;border-radius:var(--r);background-color:var(--ctl);display:grid;place-items:center;color:var(--primary-color)}
.ibtn.sel{background-color:var(--sel);box-shadow:inset 0 0 0 2px var(--primary-color)}
.srow{display:flex;align-items:center;gap:8px}
.slider{--f:.5;position:relative;flex:1;min-width:0;height:44px;border-radius:var(--r);overflow:hidden;cursor:pointer;touch-action:none;
  background:color-mix(in srgb,var(--primary-color) 20%,transparent)}
.slider .fill{position:absolute;inset:0 auto 0 0;width:calc(18px + (100% - 18px) * var(--f));background:var(--primary-color)}
.slider .hdl{position:absolute;top:50%;left:calc(18px + (100% - 18px) * var(--f) - 10px);width:4px;height:20px;margin-top:-10px;border-radius:2px;background:var(--text-primary-color,#fff)}
.slider.muted{opacity:.5}

/* steppers (number entities) */
.steps{display:grid;grid-template-columns:1fr 1fr;gap:10px 12px}
.step .lbl{margin:0 0 4px 2px}
.stepper{display:flex;align-items:center;gap:4px;padding:4px;border-radius:var(--r);background:var(--ctl)}
.stepper .ibtn{width:40px;height:36px;border-radius:var(--ir);background-color:transparent}
.stepper .v{flex:1;text-align:center;font-variant-numeric:tabular-nums;font-weight:500;white-space:nowrap}

/* toggles (switch entities) */
.tgl{display:flex;align-items:center;gap:10px;min-height:52px;padding:0 12px;border-radius:var(--r);background-color:var(--ctl);text-align:left}
.tgl .n{flex:1;min-width:0;line-height:1.25}
.tgl .n small{display:block;font-size:12px;color:var(--secondary-text-color)}
.tgl svg{color:var(--secondary-text-color)}
.tgl[aria-checked="true"]{background-color:var(--sel);box-shadow:inset 0 0 0 2px var(--primary-color)}
.tgl[aria-checked="true"] svg{color:var(--primary-color)}
.sw{position:relative;width:36px;height:14px;border-radius:7px;flex:none;margin:0 4px;background:color-mix(in srgb,var(--switch-unchecked-track-color,#000) 38%,transparent)}
.sw::after{content:"";position:absolute;top:-3px;left:-2px;width:20px;height:20px;border-radius:50%;background:var(--switch-unchecked-button-color,#fafafa);box-shadow:0 1px 3px rgba(0,0,0,.4);transition:left .15s}
[aria-checked="true"] > .sw{background:color-mix(in srgb,var(--primary-color) 50%,transparent)}
[aria-checked="true"] > .sw::after{left:18px;background:var(--primary-color)}

/* D-pad */
.dpad{--d:212px;position:relative;width:var(--d);height:var(--d);border-radius:50%;background:var(--ctl);margin:0 auto;overflow:hidden;flex:none}
.dk{position:absolute;display:grid;place-items:center;background-color:transparent;color:var(--primary-color);border-radius:var(--r)}
.dk.up{left:31%;right:31%;top:3%;height:28%}.dk.down{left:31%;right:31%;bottom:3%;height:28%}
.dk.left{top:31%;bottom:31%;left:3%;width:28%}.dk.right{top:31%;bottom:31%;right:3%;width:28%}
.dk svg{width:30px;height:30px}
.dk.ok{left:32%;top:32%;width:36%;height:36%;border-radius:50%;background-color:var(--bg);box-shadow:0 0 0 1px var(--divider-color);
  color:var(--primary-text-color);font-size:15px;font-weight:500}

/* info */
.np{display:grid;grid-template-columns:repeat(var(--n,2),minmax(0,1fr));gap:12px}
.np .k{font-size:12px;color:var(--secondary-text-color)}
.np .big{font-size:18px;line-height:1.25;font-weight:400;margin:2px 0}
.np .s{font-size:13px;color:var(--secondary-text-color);line-height:1.35}
.fld{display:flex;align-items:center;gap:10px;min-height:40px;padding:0 12px;border-radius:var(--r);background:var(--ctl)}
.fld .k{font-size:12px;color:var(--secondary-text-color)}
.fld .t{flex:1;text-align:right;font-variant-numeric:tabular-nums;letter-spacing:.06em;white-space:pre;font-weight:500}
.rows{display:flex;flex-direction:column}
.row{display:flex;align-items:center;gap:14px;min-height:30px}
.row svg{color:var(--secondary-text-color);width:20px;height:20px}
.row .n{flex:1}.row .v{color:var(--secondary-text-color);text-align:right;font-variant-numeric:tabular-nums}
.two{display:grid;grid-template-columns:1fr 1fr;gap:10px}
.setlink{display:flex;align-items:center;gap:14px;min-height:56px;padding:0 12px;border-radius:var(--r);border:1px solid var(--divider-color);background-color:transparent;text-align:left;width:100%}
.setlink .n{flex:1;line-height:1.25}.setlink .n small{display:block;font-size:12px;color:var(--secondary-text-color)}
.setlink svg{color:var(--secondary-text-color)}

/* zones */
.zhead{display:flex;align-items:center;gap:12px;min-height:44px;width:100%;text-align:left;background-color:transparent;border-radius:var(--ir);padding:0}
.zhead .n{flex:1}.zhead .n small{display:block;font-size:12px;color:var(--secondary-text-color)}

/* wider layouts */
@container (min-width:600px){
  .tabs .opt{flex-direction:row;gap:8px;min-height:44px;font-size:14px}
  .pane.p-main{justify-content:normal}
  .pane{height:auto;display:grid;grid-template-columns:1fr 1fr;align-items:start}
  .pane > .wide{grid-column:1 / -1}
  .pane .col{display:flex;flex-direction:column;gap:12px;min-width:0}
  .seg.in3{--cols:4}
  .seg.m3{--cols:4}
  .dpad{--d:236px}
}

/* ============ dialog / bottom sheet ============ */
dialog.sheet{border:0;padding:0;margin:auto auto 0;width:min(100%,480px);max-width:100%;max-height:88vh;
  background:var(--ha-dialog-surface-background,var(--card-background-color,#fff));color:var(--primary-text-color);
  border-radius:28px 28px 0 0;font-family:var(--ha-font-family-body,Roboto,system-ui,sans-serif);font-size:14px;line-height:1.4;
  --r:var(--ha-card-border-radius,12px);--ir:calc(var(--r) - 3px);--ctl:color-mix(in srgb,var(--disabled-color,#bdbdbd) 22%,transparent);
  --hov:color-mix(in srgb,var(--primary-text-color) 10%,transparent);--prs:color-mix(in srgb,var(--primary-text-color) 18%,transparent)}
dialog.sheet[open]{display:flex;flex-direction:column}
dialog.sheet::backdrop{background:rgba(0,0,0,.32)}
dialog.sheet.wide{margin:auto;border-radius:28px;width:min(560px,calc(100% - 48px))}
.handle{width:32px;height:4px;border-radius:2px;background:color-mix(in srgb,var(--primary-text-color) 30%,transparent);margin:10px auto 0}
dialog.sheet.wide .handle{display:none}
.dh{display:flex;align-items:center;gap:4px;padding:4px 12px 0 24px;min-height:56px}
.dh h2{font-size:22px;font-weight:400;margin:0;flex:1;outline:none}
.dsub{padding:0 24px 8px;margin:0;color:var(--secondary-text-color);font-size:14px}
.db{padding:4px 24px 8px;overflow:auto;display:flex;flex-direction:column;gap:2px}
.df{padding:12px 24px 20px;display:flex;gap:8px;align-items:center;border-top:1px solid var(--divider-color)}
.df .sp{flex:1}
.fbtn{min-height:44px;padding:0 22px;border-radius:22px;background-color:var(--primary-color);color:var(--text-primary-color,#fff);font-weight:500}
.fbtn[disabled]{opacity:.4;cursor:default}
.lbtn{min-height:44px;padding:0 14px;border-radius:22px;background-color:transparent;color:var(--primary-color);font-weight:500}
.xbtn{width:48px;height:48px;border-radius:50%;display:grid;place-items:center;background-color:transparent}
.rsec{font-size:13px;color:var(--secondary-text-color);padding:12px 0 4px;font-weight:500}
.rrow{display:flex;align-items:center;gap:10px;min-height:56px}
.rf{flex:1;min-width:0;position:relative}
.rf input{width:100%;height:44px;border:0;border-bottom:1px solid var(--secondary-text-color);border-radius:var(--ir) var(--ir) 0 0;
  background:var(--ctl);color:var(--primary-text-color);font:inherit;font-size:15px;padding:0 12px}
.rf input:focus{outline:none;border-bottom:2px solid var(--primary-color)}
.rf input.bad{border-bottom:2px solid var(--error-color)}
.rf .err{font-size:12px;color:var(--error-color);padding:2px 12px 0}
.rrow.hid input{color:var(--secondary-text-color)}
.hnd{touch-action:none;display:grid;place-items:center;width:28px;height:44px;margin-left:-8px;color:var(--secondary-text-color);cursor:grab;flex:none}
.rrow.drag{opacity:.5}
.rshow{display:flex;align-items:center;gap:6px;min-height:44px;padding:0 4px;background-color:transparent;border-radius:22px;font-size:12px;color:var(--secondary-text-color)}
.cur{font-size:11px;color:var(--primary-color);padding:2px 12px 0}


.panelwrap{--r:var(--ha-card-border-radius,12px);--ir:calc(var(--r) - 3px);
  --ctl:color-mix(in srgb,var(--disabled-color,#bdbdbd) 22%,transparent);
  --hov:color-mix(in srgb,var(--primary-text-color,#212121) 10%,transparent);
  --prs:color-mix(in srgb,var(--primary-text-color,#212121) 18%,transparent);
  --sel:color-mix(in srgb,var(--primary-color,#009ac7) 20%,transparent)}
@media (prefers-reduced-motion:reduce){*{animation:none !important;transition:none !important}}
`;
