const $=(selector,root=document)=>root.querySelector(selector);
const $$=(selector,root=document)=>[...root.querySelectorAll(selector)];

function refreshIcons(){if(window.lucide)window.lucide.createIcons()}

function endpoint(name,fallback){return document.body?.dataset?.[name]||fallback}
function staticAsset(path){const base=document.body?.dataset?.staticBase||"/static/";return `${base.replace(/\/?$/,"/")}${path.replace(/^\//,"")}`}
function escapeHtml(value){return String(value??"").replace(/[&<>"']/g,char=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[char]))}
function csrfHeaders(headers={}){return {...headers,"X-CSRFToken":document.body?.dataset?.csrfToken||""}}

function setupPrincipleFormula(){
  const element=$("[data-principle-formula]");if(!element)return;
  const source=(element.dataset.formula||element.textContent||"").trim();if(!source){element.textContent="";return}
  if(!window.katex){element.textContent=source;return}
  const latex=source
    .replace(/\bomega\b/gi,"\\omega")
    .replace(/\b([A-Za-z]+)(\d+)\b/g,"$1_{$2}")
    .replace(/\*\*\s*([+-]?\d+(?:\.\d+)?)/g,"^{$1}")
    .replace(/\s+\*\s+/g," \\cdot ");
  try{const rendered=window.katex.renderToString(latex,{throwOnError:false,displayMode:true,strict:"ignore",trust:false});if(rendered.includes('class="katex-error"'))throw new Error("公式格式无效");element.innerHTML=rendered}catch{element.textContent=source}
}

function setupAcademicFormulas(){
  $$('[data-academic-formula]').forEach(element=>{const source=element.textContent.trim();if(!source||!window.katex)return;try{element.innerHTML=window.katex.renderToString(source,{throwOnError:false,displayMode:true,strict:"ignore",trust:false})}catch{element.textContent=source}})
}

function openModal(name){const modal=document.querySelector(`[data-modal="${name}"]`);if(!modal)return;modal.classList.remove("is-hidden");document.body.style.overflow="hidden";refreshIcons()}
function closeModal(modal){if(!modal)return;modal.classList.add("is-hidden");if(!document.querySelector(".modal-backdrop:not(.is-hidden)"))document.body.style.overflow=""}

function activateTab(name){
  const tabs=$("[data-tabs]");if(!tabs)return;
  $$('[data-tab-target]',tabs).forEach(button=>button.classList.toggle("active",button.dataset.tabTarget===name));
  $$('[data-tab-panel]').forEach(panel=>panel.classList.toggle("active",panel.dataset.tabPanel===name));
  window.scrollTo({top:Math.max(0,tabs.offsetTop-72),behavior:"smooth"});
  document.dispatchEvent(new CustomEvent("workspace:tab",{detail:{name}}));
}

function setupWorkspaceStepNavigation(){
  const nav=$("[data-workspace-step-nav]"),tabs=$("[data-tabs]");if(!nav||!tabs)return;
  const order=$$('[data-tab-target]',tabs).map(button=>button.dataset.tabTarget),previous=$("[data-workspace-prev]",nav),next=$("[data-workspace-next]",nav),label=$("[data-workspace-step-label]",nav);
  const update=name=>{const index=Math.max(0,order.indexOf(name));previous.disabled=index===0;next.disabled=index===order.length-1;label.textContent=`第 ${index+1} 步 / 共 ${order.length} 步`;previous.querySelector("span").textContent=index?`上一步：${$(`[data-tab-target="${order[index-1]}"]`,tabs)?.querySelector("b")?.textContent||""}`:"已是第一步";next.querySelector("span").textContent=index<order.length-1?`下一步：${$(`[data-tab-target="${order[index+1]}"]`,tabs)?.querySelector("b")?.textContent||""}`:"已是最后一步"};
  const active=()=>$("[data-tab-target].active",tabs)?.dataset.tabTarget||order[0];
  previous.addEventListener("click",()=>{const index=order.indexOf(active());if(index>0)activateTab(order[index-1])});next.addEventListener("click",()=>{const index=order.indexOf(active());if(index<order.length-1)activateTab(order[index+1])});document.addEventListener("workspace:tab",event=>update(event.detail.name));update(active());
}

function setupStudentRecords(){
  const root=$("[data-student-records]");if(!root)return;const controls=$$("[data-record-filter]",root),rows=$$("[data-record-state]",root),empty=$("[data-record-empty]",root);
  controls.forEach(control=>control.addEventListener("click",()=>{const filter=control.dataset.recordFilter;controls.forEach(item=>item.classList.toggle("active",item===control));let visible=0;rows.forEach(row=>{const matches=filter==="all"||row.dataset.recordState===filter;row.hidden=!matches;if(matches)visible++});empty?.classList.toggle("is-hidden",visible>0)}));
}

function setupAutoOpenModal(){
  const backdrop=$("[data-auto-open-modal]");if(!backdrop)return;
  const dialog=$(".dialog-card",backdrop);const previouslyFocused=document.activeElement;
  const restoreFocus=()=>{(previouslyFocused&&previouslyFocused.focus?previouslyFocused:document.body).focus?.()};
  const observer=new MutationObserver(()=>{if(backdrop.classList.contains("is-hidden")){observer.disconnect();restoreFocus()}});
  observer.observe(backdrop,{attributes:true,attributeFilter:["class"]});
  backdrop.addEventListener("click",event=>{if(event.target===backdrop)closeModal(backdrop)});
  if("replaceState" in history){const url=new URL(window.location.href);url.searchParams.delete(backdrop.dataset.autoOpenModal==="certificate"?"certificate":backdrop.dataset.autoOpenModal);history.replaceState(null,"",url.pathname+url.search)}
  openModal(backdrop.dataset.modal);
  dialog?.focus();
}

function setupQuiz(){
  const form=$("[data-quiz-form]");if(!form)return;
  const questions=$$("[data-quiz-question]",form),position=$("[data-quiz-position]",form),bar=$("[data-quiz-progress]",form),prev=$("[data-quiz-prev]",form),next=$("[data-quiz-next]",form),submit=$("[data-quiz-submit]",form);let index=0;
  const render=()=>{questions.forEach((q,i)=>q.classList.toggle("active",i===index));position.textContent=`第 ${index+1} / ${questions.length} 题`;bar.style.width=`${((index+1)/questions.length)*100}%`;prev.disabled=index===0;next.hidden=index===questions.length-1;if(submit)submit.hidden=index!==questions.length-1;refreshIcons()};
  next.addEventListener("click",()=>{const selected=$("input:checked",questions[index]);if(!selected){questions[index].classList.add("needs-answer");return}questions[index].classList.remove("needs-answer");index=Math.min(index+1,questions.length-1);render()});
  prev.addEventListener("click",()=>{index=Math.max(0,index-1);render()});render();
}

function presetFit(experiment,template){
  if(template==="sine")return `import numpy as np\nimport matplotlib.pyplot as plt\nfrom scipy.optimize import curve_fit\n\ndef model(theta, a, b, phi):\n    return a + b*np.cos(2*theta + phi)**2\n\nparams, _ = curve_fit(model, x, y, p0=[float(np.mean(y)), float(np.ptp(y)), 0.0], maxfev=20000)\ny_fit = model(np.asarray(x), *params)\nss_res = float(np.sum((np.asarray(y)-y_fit)**2))\nss_tot = float(np.sum((np.asarray(y)-np.mean(y))**2))\nr2 = 1-ss_res/ss_tot if ss_tot else 1.0\nresult = {'final_parameters': {'a': float(params[0]), 'b': float(params[1]), 'phi': float(params[2])}, 'metrics': {'r2': r2}}\norder=np.argsort(x)\nplt.figure(figsize=(7,4)); plt.scatter(x,y,label='测量数据'); plt.plot(np.asarray(x)[order],y_fit[order],label='拟合曲线'); plt.legend(); plt.grid(alpha=.2)`;
  if(template==="odmr")return `import numpy as np\nimport matplotlib.pyplot as plt\nfrom scipy.optimize import curve_fit\n\ndef model(f, c, a, f0, gamma):\n    return c-a/(1+((f-f0)/gamma)**2)\n\nx_arr=np.asarray(x,dtype=float); y_arr=np.asarray(y,dtype=float)\np0=[float(np.max(y_arr)),float(np.ptp(y_arr)),float(x_arr[np.argmin(y_arr)]),max(float(np.ptp(x_arr))/10,1e-6)]\nparams,_=curve_fit(model,x_arr,y_arr,p0=p0,maxfev=30000)\ny_fit=model(x_arr,*params)\nss_res=float(np.sum((y_arr-y_fit)**2)); ss_tot=float(np.sum((y_arr-y_arr.mean())**2))\nresult={'final_parameters':{'c':float(params[0]),'a':float(params[1]),'f0':float(params[2]),'gamma':float(params[3])},'metrics':{'r2':1-ss_res/ss_tot if ss_tot else 1.0}}\norder=np.argsort(x_arr)\nplt.figure(figsize=(7,4)); plt.scatter(x_arr,y_arr,label='测量数据'); plt.plot(x_arr[order],y_fit[order],label='ODMR 拟合'); plt.legend(); plt.grid(alpha=.2)`;
  if(experiment.includes("量子密钥分发"))return `import numpy as np\nimport matplotlib.pyplot as plt\nerrors=np.asarray(x,dtype=float); sifted=np.asarray(y,dtype=float)\nqber=np.divide(errors,sifted,out=np.zeros_like(errors),where=sifted!=0)\nresult={'final_parameters':{'mean_qber':float(np.mean(qber))},'metrics':{'points':int(len(qber))}}\nplt.figure(figsize=(7,4)); plt.plot(range(1,len(qber)+1),qber,'o-'); plt.axhline(.11,color='#b7343b',linestyle='--',label='11% 参考线'); plt.xlabel('数据组'); plt.ylabel('QBER'); plt.legend(); plt.grid(alpha=.2)`;
  return `import numpy as np\nimport matplotlib.pyplot as plt\nx_arr=np.asarray(x,dtype=float); y_arr=np.asarray(y,dtype=float)\np1,p2=np.polyfit(x_arr,y_arr,1)\ny_fit=p1*x_arr+p2\nss_res=float(np.sum((y_arr-y_fit)**2)); ss_tot=float(np.sum((y_arr-y_arr.mean())**2))\nr2=1-ss_res/ss_tot if ss_tot else 1.0\nresult={'final_parameters':{'p1':float(p1),'p2':float(p2)},'metrics':{'r2':r2,'rmse':float(np.sqrt(np.mean((y_arr-y_fit)**2)))}}\norder=np.argsort(x_arr)\nplt.figure(figsize=(7,4)); plt.scatter(x_arr,y_arr,label='测量数据'); plt.plot(x_arr[order],y_fit[order],label='线性拟合'); plt.xlabel('x'); plt.ylabel('y'); plt.legend(); plt.grid(alpha=.2)`;
}

function withTimeout(promise,milliseconds,message){
  let timer;
  return Promise.race([promise,new Promise((_,reject)=>{timer=setTimeout(()=>reject(new Error(message)),milliseconds)})]).finally(()=>clearTimeout(timer));
}

async function preparePyodide(setState){
  setState("正在加载浏览器计算引擎…首次运行通常需要 30–90 秒");
  const runtime=await withTimeout(loadPyodide(),120000,"计算引擎加载超时，请检查网络后重试");
  setState("正在准备 NumPy、SciPy、Matplotlib 和 Pandas…");
  await withTimeout(runtime.loadPackage(["numpy","scipy","matplotlib","pandas"]),120000,"科学计算组件加载超时，请检查网络后重试");
  setState("正在配置中文图表字体…");
  if(!runtime.FS.analyzePath("/tmp/simhei.ttf").exists){
    const response=await fetch(staticAsset("fonts/simhei.ttf"));
    if(!response.ok)throw new Error("中文图表字体加载失败");
    runtime.FS.writeFile("/tmp/simhei.ttf",new Uint8Array(await response.arrayBuffer()));
  }
  await runtime.runPythonAsync("from matplotlib import font_manager, rcParams\nfont_manager.fontManager.addfont('/tmp/simhei.ttf')\nrcParams['font.sans-serif']=['SimHei']\nrcParams['axes.unicode_minus']=False");
  setState("计算环境已就绪 · 填完数据会自动拟合");
  return runtime;
}

function setupFit(){
  const root=$("[data-fit-workspace]");if(!root)return;
  const rows=$("[data-fit-rows]",root),head=$("[data-fit-head] tr",root),data=$("[data-fit-data]",root),formula=$("[data-fit-formula]",root),initial=$("[data-fit-initial]",root),code=$("[data-fit-code]",root),editor=$("[data-fit-code-editor]"),state=$("[data-fit-state]",root),output=$("[data-fit-output]",root),placeholder=$("[data-fit-placeholder]",root),fitHidden=$("[data-fit-result]",root),submitHidden=$("[data-fit-result-submit]"),rawData=$("[data-raw-data]"),autoRun=$("[data-fit-auto]",root);let pyodide,pyodidePromise,autoTimer;
  const template=root.dataset.fitTemplate||"linear";const defaults=presetFit(root.dataset.exp,template);code.value=defaults;if(editor)editor.value=defaults;
  initial.value=template==="sine"?'{"a": 1.0, "b": 1.0, "phi": 0.0}':template==="odmr"?'{"c": 1.0, "a": 0.1, "f0": 2.87, "gamma": 0.01}':'{"p1": -0.5, "p2": 0.0}';
  const getColumns=()=>{try{return JSON.parse(rows.dataset.fitColumns)}catch{return[rows.dataset.xLabel||"x",rows.dataset.yLabel||"y"]}};
  const setColumns=cols=>{rows.dataset.fitColumns=JSON.stringify(cols);return cols};
  const sync=()=>{const cols=getColumns();const values=$$("tr",rows).map(row=>cols.map((_,i)=>$(`[data-fit-col="${i}"]`,row)?.value.trim()||"").filter((_,i,arr)=>arr.some(v=>v!=="")?true:i<2)).filter(row=>row.some(v=>v!==""));data.value=values.map(row=>row.join(",")).join("\n");if(rawData&&!rawData.dataset.userEdited)rawData.value=data.value;return values};
  const completePairs=()=>{const rows=sync();return rows.length>=2&&rows.every(row=>row.length>=2&&row.slice(0,2).every(value=>value!==""&&Number.isFinite(Number(value))))?rows:null};
  const ensureRuntime=()=>pyodidePromise||(pyodidePromise=preparePyodide(message=>state.textContent=message).then(runtime=>(pyodide=runtime,runtime)).catch(error=>{pyodidePromise=null;throw error}));
  const addRow=(...values)=>{const cols=getColumns();const tr=document.createElement("tr"),number=rows.children.length+1;let html=`<td>${String(number).padStart(2,"0")}</td>`;cols.forEach((col,i)=>{html+=`<td><input inputmode="decimal" data-fit-col="${i}" aria-label="第 ${number} 行${col}" value="${values[i]||""}"></td>`});tr.innerHTML=html;rows.appendChild(tr)};
  const rebuildHeader=()=>{const cols=getColumns();let h=`<th>序号</th>`;cols.forEach((col,i)=>h+=`<th class="fit-col-header" data-fit-col-header="${i}" title="双击重命名，右键删除"><span>${col}</span></th>`);head.innerHTML=h};
  const addColumn=(name="")=>{const cols=getColumns();const label=name||`列${cols.length+1}`;setColumns([...cols,label]);rebuildHeader();$$("tr",rows).forEach(row=>{const td=document.createElement("td");td.innerHTML=`<input inputmode="decimal" data-fit-col="${cols.length}" aria-label="第 ${[...rows.children].indexOf(row)+1} 行${label}">`;row.appendChild(td)});sync();scheduleAutoRun()};
  const removeColumn=(index)=>{const cols=getColumns();if(cols.length<=2)return;cols.splice(index,1);setColumns(cols);rebuildHeader();$$("tr",rows).forEach(row=>{const inputs=$$("[data-fit-col]",row);inputs.forEach(inp=>{const i=parseInt(inp.dataset.fitCol);if(i===index)inp.parentElement.remove();else if(i>index)inp.dataset.fitCol=String(i-1)})});sync();scheduleAutoRun()};
  const scheduleAutoRun=()=>{clearTimeout(autoTimer);if(!autoRun?.checked||!completePairs())return;state.textContent="数据已完整 · 即将自动拟合";autoTimer=setTimeout(()=>runFit({silentInvalid:true}),700)};
  rows.addEventListener("input",()=>{sync();scheduleAutoRun()});
  head.addEventListener("dblclick",event=>{const th=event.target.closest(".fit-col-header");if(!th)return;const i=parseInt(th.dataset.fitColHeader);const cols=getColumns();const span=th.querySelector("span");const input=document.createElement("input");input.value=cols[i];input.style.cssText="border:1px solid var(--jade);padding:2px 6px;font-size:11px;width:100%;text-align:center;border-radius:4px";span.replaceWith(input);input.focus();input.select();const save=()=>{const v=input.value.trim();if(v){cols[i]=v;setColumns(cols)}const newSpan=document.createElement("span");newSpan.textContent=v||cols[i];input.replaceWith(newSpan);sync()};input.addEventListener("blur",save);input.addEventListener("keydown",e=>{if(e.key==="Enter"){e.preventDefault();save()}if(e.key==="Escape"){input.value=cols[i];save()}})});
  head.addEventListener("contextmenu",event=>{const th=event.target.closest(".fit-col-header");if(!th)return;event.preventDefault();if(getColumns().length<=2)return;const i=parseInt(th.dataset.fitColHeader);removeColumn(i)});
  $("[data-add-fit-row]",root)?.addEventListener("click",()=>addRow());
  $("[data-add-fit-column]",root)?.addEventListener("click",()=>addColumn());
  $("[data-paste-fit]",root)?.addEventListener("click",async()=>{try{const text=await navigator.clipboard.readText();const parsed=text.trim().split(/\n+/).map(line=>line.trim().split(/[,\s;]+/));if(!parsed.length)throw new Error("剪贴板中没有数据");rows.innerHTML="";const maxCols=Math.max(...parsed.map(r=>r.length),2);let cols=getColumns();while(cols.length<maxCols){cols.push(`列${cols.length+1}`)}setColumns(cols);rebuildHeader();parsed.forEach(pair=>addRow(...pair));sync();scheduleAutoRun()}catch(error){state.textContent=`无法粘贴：${error.message}`}});
  rawData?.addEventListener("input",()=>rawData.dataset.userEdited="true");
  $("[data-reset-fit-code]")?.addEventListener("click",()=>{code.value=defaults;editor.value=defaults});
  $("[data-save-fit-code]")?.addEventListener("click",()=>{code.value=editor.value;closeModal($("[data-modal='fit-code']"));scheduleAutoRun()});
  const runButton=$("[data-run-fit]",root);
  async function runFit({silentInvalid=false}={}){if(runButton.disabled)return;clearTimeout(autoTimer);const rowData=completePairs();if(!rowData){if(!silentInvalid)state.textContent="请填写至少两行完整的数值数据";return}runButton.disabled=true;runButton.setAttribute("aria-busy","true");try{const cols=getColumns();const x=rowData.map(row=>Number(row[0])),y=rowData.map(row=>Number(row[1]));const extra={};for(let i=2;i<cols.length;i++)extra[`col_${cols[i]}`]=rowData.map(row=>row[i]?Number(row[i]):null).filter(v=>v!==null);pyodide=await ensureRuntime();state.textContent="正在检查代码所需模块…";await withTimeout(pyodide.loadPackagesFromImports(code.value),120000,"代码依赖模块加载超时");state.textContent="模块已就绪 · 正在执行拟合并生成图表…";pyodide.globals.set("x",pyodide.toPy(x));pyodide.globals.set("y",pyodide.toPy(y));for(const[k,v]of Object.entries(extra))if(v.length)pyodide.globals.set(k,pyodide.toPy(v));await withTimeout(pyodide.runPythonAsync(code.value),60000,"拟合执行超时，请检查数据或预置代码");const json=await pyodide.runPythonAsync(`import json, io, base64\n_buf=io.BytesIO()\nplt.gcf().savefig(_buf,format='png',dpi=140,bbox_inches='tight')\njson.dumps({'final_parameters':result.get('final_parameters',{}),'metrics':result.get('metrics',{}),'plot_data_url':'data:image/png;base64,'+base64.b64encode(_buf.getvalue()).decode()})`);const fit=JSON.parse(json);fit.code=code.value;fit.formula=formula.value;fit.initial_parameters=JSON.parse(initial.value||"{}");const check=await fetch(endpoint("fittingValidateUrl","/api/fitting/validate"),{method:"POST",headers:csrfHeaders({"Content-Type":"application/json"}),body:JSON.stringify(fit)});const checked=await check.json();if(!check.ok)throw new Error(checked.error||"结果校验失败");const value=JSON.stringify(checked.result);fitHidden.value=value;if(submitHidden)submitHidden.value=value;output.hidden=false;placeholder.hidden=true;$("img",output).src=checked.result.plot_data_url;$("pre",output).textContent=JSON.stringify({final_parameters:checked.result.final_parameters,metrics:checked.result.metrics},null,2);state.textContent="拟合完成 · 结果已自动附入报告";$(".fit-result-card .status",root).textContent="拟合成功";$(".fit-result-card .status",root).className="status published"}catch(error){const missing=String(error.message).match(/(?:No module named|ModuleNotFoundError:?)[ '\"]+([^'\"\\s]+)/i);state.textContent=missing?`无法自动运行：浏览器环境未提供模块 ${missing[1]}，请改用已预装模块或联系教师调整代码`:`运行失败：${error.message}`}finally{runButton.disabled=false;runButton.removeAttribute("aria-busy")}}
  runButton?.addEventListener("click",()=>runFit());
  autoRun?.addEventListener("change",()=>{state.textContent=autoRun.checked?"自动拟合已开启 · 数据完整后直接运行":"自动拟合已关闭 · 可点击运行";if(autoRun.checked)scheduleAutoRun()});
  document.addEventListener("workspace:tab",event=>{if(event.detail.name!=="fit")return;ensureRuntime().catch(error=>state.textContent=`计算环境准备失败：${error.message}`);scheduleAutoRun()});
  rebuildHeader();sync();
}

function setupFilters(){
  const search=$("[data-table-search]"),table=$("[data-filter-table]"),status=$("[data-table-status]"),course=$("[data-table-course]"),sort=$("[data-table-sort]");if(!search||!table)return;
  const filter=()=>{const query=search.value.trim().toLowerCase(),wanted=status?.value||"",courseId=course?.value||"";$$('tbody tr',table).forEach(row=>{row.hidden=Boolean(query&&!row.textContent.toLowerCase().includes(query))||Boolean(wanted&&row.dataset.status!==wanted)||Boolean(courseId&&row.dataset.course!==courseId)})};
  search.addEventListener("input",filter);status?.addEventListener("change",filter);course?.addEventListener("change",filter);
  sort?.addEventListener("click",()=>{const ascending=sort.getAttribute("aria-pressed")!=="true",body=$("tbody",table),rows=$$("tr[data-sort-value]",body);rows.sort((a,b)=>ascending?a.dataset.sortValue.localeCompare(b.dataset.sortValue):b.dataset.sortValue.localeCompare(a.dataset.sortValue)).forEach(row=>body.appendChild(row));sort.setAttribute("aria-pressed",String(ascending));sort.setAttribute("aria-label",ascending?"按提交时间降序排列":"按提交时间升序排列");sort.lastChild.textContent=ascending?" 提交时间：旧到新":" 提交时间：新到旧"});
}

function setupExperimentDraftAssistant(){
  const form=$("[data-experiment-ai-form]"),prompt=$("[data-experiment-prompt]"),voice=$("[data-experiment-voice]"),state=$("[data-experiment-voice-state]"),mode=$("[data-experiment-input-mode]"),material=$("[data-experiment-material]"),generate=$("[data-experiment-generate]");
  if(!form)return;
  const Recognition=window.SpeechRecognition||window.webkitSpeechRecognition;let recognition,listening=false,baseText="";
  const finish=message=>{listening=false;voice.classList.remove("listening");voice.querySelector("span").textContent="语音输入";if(message)state.textContent=message};
  voice.addEventListener("click",()=>{
    if(!Recognition){state.textContent="当前浏览器不支持语音转写，请使用最新版 Chrome/Edge 或直接输入文字。";return}
    if(listening){recognition.stop();return}
    recognition=new Recognition();recognition.lang="zh-CN";recognition.continuous=false;recognition.interimResults=true;baseText=prompt.value.trim();
    recognition.onstart=()=>{listening=true;mode.value="voice";voice.classList.add("listening");voice.querySelector("span").textContent="正在聆听…";state.textContent="请说出实验名称、实验代码、实验目标和主要操作。再次点击可结束。"};
    recognition.onresult=event=>{let transcript="";for(let index=event.resultIndex;index<event.results.length;index++)transcript+=event.results[index][0].transcript;prompt.value=[baseText,transcript].filter(Boolean).join(baseText?"\n":"")};
    recognition.onerror=event=>finish(event.error==="not-allowed"?"麦克风权限未开启，请在浏览器地址栏允许后重试。":"语音识别没有完成，请重试或直接输入文字。");
    recognition.onend=()=>finish(prompt.value.trim()?"语音已转成文字，可以继续修改或直接生成草稿。":"没有识别到内容，请靠近麦克风后重试。");recognition.start();
  });
  material?.addEventListener("change",()=>{const file=material.files[0];if(file){state.textContent=`已选择材料：${file.name}`;mode.value="material"}});
  form.addEventListener("submit",event=>{if(!prompt.value.trim()&&!material?.files.length){event.preventDefault();state.textContent="请先描述实验，或选择一份实验材料。";prompt.focus();return}generate.disabled=true;generate.setAttribute("aria-busy","true");generate.innerHTML='<i data-lucide="loader-circle"></i> 正在解析并生成实验草稿…';refreshIcons()});
}

function setupEditor(){
  const root=$("[data-editor]");if(!root)return;
  const buttons=$$('[data-editor-target]',root),panels=$$('[data-editor-panel]',root),previous=$("[data-editor-previous]",root),next=$("[data-editor-next]",root),label=$("[data-editor-flow-label]",root);
  const activate=(target,scroll=false)=>{const index=Math.max(0,buttons.findIndex(button=>button.dataset.editorTarget===target));buttons.forEach((button,position)=>button.classList.toggle("active",position===index));panels.forEach(panel=>panel.classList.toggle("active",panel.dataset.editorPanel===buttons[index].dataset.editorTarget));if(previous)previous.disabled=index===0;if(next)next.disabled=index===buttons.length-1;if(label)label.textContent=`第 ${index+1} 步 / 共 ${buttons.length} 步`;if(scroll&&window.matchMedia("(max-width: 720px)").matches)root.scrollIntoView({behavior:window.matchMedia("(prefers-reduced-motion: reduce)").matches?"auto":"smooth",block:"start"})};
  buttons.forEach(button=>button.addEventListener("click",()=>activate(button.dataset.editorTarget)));
  previous?.addEventListener("click",()=>{const index=buttons.findIndex(button=>button.classList.contains("active"));if(index>0)activate(buttons[index-1].dataset.editorTarget,true)});
  next?.addEventListener("click",()=>{const index=buttons.findIndex(button=>button.classList.contains("active"));if(index<buttons.length-1)activate(buttons[index+1].dataset.editorTarget,true)});
  activate(buttons.find(button=>button.classList.contains("active"))?.dataset.editorTarget||buttons[0]?.dataset.editorTarget);
}

function setupQuestionManager(){
  const root=$("[data-question-manager]");if(!root)return;
  const source=$("[data-question-json]",root),list=$("[data-question-list]",root),search=$("[data-question-search]",root),empty=$("[data-question-empty]",root),form=$("[data-question-form]",root),message=$("[data-question-message]",root),total=$("[data-question-total]",root),reviewed=$("[data-question-reviewed]",root);
  const fields=Object.fromEntries($$("[data-question-field]",form).map(field=>[field.dataset.questionField,field])),options=$$("[data-question-option]",form),answer=fields.answer;
  let questions=[];try{questions=JSON.parse(source.value||"[]")}catch{message.textContent="题库读取失败，请刷新页面后重试。"}
  questions=Array.isArray(questions)?questions:[];let activeId=questions[0]?.id||null;
  const uniqueId=()=>{let index=questions.length+1,id;do{id=`manual-${Date.now()}-${index++}`}while(questions.some(item=>item.id===id));return id};
  const activeQuestion=()=>questions.find(item=>item.id===activeId);
  const syncSource=()=>{source.value=JSON.stringify(questions);total.textContent=String(questions.length);reviewed.textContent=String(questions.filter(item=>item.reviewed_by_teacher).length)};
  const renderAnswerChoices=(selected="")=>{answer.textContent="";const placeholder=document.createElement("option");placeholder.value="";placeholder.textContent="请选择正确答案";answer.appendChild(placeholder);["A","B","C","D"].forEach((letter,position)=>{const option=document.createElement("option");option.value=String(position);option.textContent=`${letter} · ${options[position].value||"未填写"}`;answer.appendChild(option)});answer.value=selected};
  const readEditor=(validate=false)=>{
    const item=activeQuestion();if(!item)return true;
    const nextOptions=options.map(input=>input.value.trim()),answerIndex=Number(answer.value);
    if(validate&&(!fields.question.value.trim()||nextOptions.some(value=>!value)||new Set(nextOptions).size!==4||!Number.isInteger(answerIndex)||answerIndex<0||answerIndex>3||fields.explanation.value.trim().length<8)){
      message.textContent="请完整填写题干、4 个不重复选项、正确答案，并提供至少 8 个字的答案解析。";message.classList.add("error");return false;
    }
    Object.assign(item,{question:fields.question.value.trim(),options:nextOptions,answer:nextOptions[answerIndex]||"",explanation:fields.explanation.value.trim(),concept_title:fields.concept_title.value.trim(),concept_id:fields.concept_id.value.trim()});
    if(validate)item.reviewed_by_teacher=true;syncSource();return true;
  };
  const renderEditor=()=>{
    const item=activeQuestion(),disabled=!item;$$('input,textarea,select,button[data-question-save],button[data-question-delete]',form).forEach(control=>control.disabled=disabled);
    if(!item){$("[data-question-position]",form).textContent="暂无题目";$("[data-question-heading]",form).textContent="可手动添加，或使用右侧 AI 题库助手";$("[data-question-status]",form).textContent="待添加";Object.values(fields).forEach(field=>field.value="");options.forEach(input=>input.value="");answer.textContent='<option value="">请选择正确答案</option>';return}
    const index=questions.indexOf(item);$("[data-question-position]",form).textContent=`第 ${index+1} 题 / 共 ${questions.length} 题`;$("[data-question-heading]",form).textContent=item.concept_title||"未命名知识点";const status=$("[data-question-status]",form);status.textContent=item.reviewed_by_teacher?"已审核":"待审核";status.classList.toggle("reviewed",Boolean(item.reviewed_by_teacher));
    fields.question.value=item.question||"";fields.explanation.value=item.explanation||"";fields.concept_title.value=item.concept_title||item.mother_question||"";fields.concept_id.value=item.concept_id||"";
    options.forEach((input,position)=>{input.value=item.options?.[position]||""});const answerIndex=(item.options||[]).indexOf(item.answer);renderAnswerChoices(answerIndex>=0?String(answerIndex):"");message.textContent="";message.classList.remove("error");
  };
  const renderList=()=>{
    const query=search.value.trim().toLowerCase();list.textContent="";let visible=0;
    questions.forEach((item,index)=>{const haystack=`${item.question||""} ${item.concept_title||""} ${item.concept_id||""}`.toLowerCase();if(query&&!haystack.includes(query))return;visible++;const button=document.createElement("button");button.type="button";button.className=`question-list-item${item.id===activeId?" active":""}`;button.dataset.questionId=item.id;const number=document.createElement("span");number.textContent=String(index+1).padStart(2,"0");const copy=document.createElement("span");const title=document.createElement("b");title.textContent=item.question||"未填写题干";const meta=document.createElement("small");meta.textContent=`${item.concept_title||"未分知识点"} · ${item.reviewed_by_teacher?"已审核":"待审核"}`;copy.append(title,meta);button.append(number,copy);list.appendChild(button)});empty.hidden=visible>0;syncSource();
  };
  list.addEventListener("click",event=>{const button=event.target.closest("[data-question-id]");if(!button)return;readEditor(false);activeId=button.dataset.questionId;renderList();renderEditor()});
  search.addEventListener("input",renderList);
  options.forEach(input=>input.addEventListener("input",()=>renderAnswerChoices(answer.value)));
  $("[data-question-add]",root).addEventListener("click",()=>{readEditor(false);const id=uniqueId();questions.push({id,concept_id:"",concept_title:"",question:"",options:["","","",""],answer:"",explanation:"",reviewed_by_teacher:false});activeId=id;search.value="";renderList();renderEditor();fields.question.focus()});
  $("[data-question-save]",form).addEventListener("click",()=>{if(!readEditor(true))return;message.textContent="本题已保存并标记为已审核。";message.classList.remove("error");renderList();renderEditor()});
  $("[data-question-delete]",form).addEventListener("click",()=>{const item=activeQuestion();if(!item||!window.confirm("确认删除当前题目？保存草稿后删除才会生效。"))return;const index=questions.indexOf(item);questions.splice(index,1);activeId=questions[index]?.id||questions[index-1]?.id||null;renderList();renderEditor()});
  $("#experimentEditForm")?.addEventListener("submit",()=>{readEditor(false);syncSource()});
  renderList();renderEditor();
}

function setupReportEditor(){
  const root=$("[data-report-editor]");if(!root)return;
  const source=$("[data-report-document]",root),state=$("[data-report-save-state]"),paper=$("[data-report-live-paper]",root),locked=root.dataset.locked==="true",storageKey=`report-draft-recovery:${root.dataset.code}`;
  let model;try{model=JSON.parse(source.textContent)}catch{state.textContent="报告草稿读取失败";return}
  let lockVersion=Number(source.closest(".report-authoring-panel")?.querySelector('[name="draft_id"]')?0:0),activeSection="purpose",saveTimer=null,savePromise=null,dirty=false,conflicted=false,submitting=false;
  const draftId=$('[name="draft_id"]',root)?.value;lockVersion=Number(root.dataset.lockVersion||1);
  const mediaUrl=hash=>(root.dataset.mediaTemplate||"/media/__HASH__").replace("__HASH__",hash);
  const setState=(text,kind="")=>{state.textContent=text;state.className=`report-save-state ${kind}`.trim()};
  const element=(tag,className,text)=>{const node=document.createElement(tag);if(className)node.className=className;if(text!==undefined)node.textContent=text;return node};
  const appendRuns=(target,block)=>{const runs=Array.isArray(block.runs)&&block.runs.length?block.runs:[{text:block.text||"",marks:[]}];runs.forEach(run=>{let node=document.createTextNode(run.text||"");(run.marks||[]).forEach(mark=>{const tag={bold:"strong",italic:"em",underline:"u",superscript:"sup",subscript:"sub"}[mark];if(tag){const wrapper=document.createElement(tag);wrapper.appendChild(node);node=wrapper}});target.appendChild(node)})};
  const normalizeFormula=value=>String(value||"").replace(/\*\*/g,"^").replace(/\bomega\b/gi,"\\omega").replace(/(?<!\\)\*/g,"\\cdot ");
  const renderFormula=(target,latex)=>{const source=normalizeFormula(latex);target.textContent="";if(window.katex){try{target.innerHTML=window.katex.renderToString(source,{throwOnError:false,displayMode:true,strict:"ignore",trust:false});return}catch{}}target.textContent=latex||""};
  const editorBlock=block=>{
    if(["paragraph","heading","quote"].includes(block.type)){const node=element(block.type==="heading"?"h4":block.type==="quote"?"blockquote":"p");appendRuns(node,block);if(block.alignment)node.style.textAlign=block.alignment;return node}
    if(block.type==="list"){const list=element(block.ordered?"ol":"ul");(block.items||[]).forEach(item=>list.appendChild(element("li","",item)));return list}
    if(block.type==="formula"){const box=element("div","report-editor-formula");box.dataset.latex=block.latex||"";box.contentEditable="false";renderFormula(box,box.dataset.latex);if(block.caption)box.appendChild(element("small","",block.caption));return box}
    if(block.type==="table"){const wrap=element("figure","report-editor-table"),table=element("table");(block.rows||[]).forEach((row,rowIndex)=>{const tr=element("tr");row.forEach(cell=>{const td=element(rowIndex===0?"th":"td","",cell);tr.appendChild(td)});table.appendChild(tr)});wrap.appendChild(table);if(block.caption)wrap.appendChild(element("figcaption","",block.caption));return wrap}
    if(block.type==="image"){const figure=element("figure","report-editor-image");figure.dataset.assetHash=block.asset_hash;figure.dataset.width=String(block.width||80);figure.dataset.alignment=block.alignment||"center";figure.contentEditable="false";const img=element("img");img.src=mediaUrl(block.asset_hash);img.alt=block.caption||"实验图片";img.style.width=`${block.width||80}%`;figure.appendChild(img);if(block.caption)figure.appendChild(element("figcaption","",block.caption));return figure}
    if(block.type==="fit_plot"){const figure=element("figure","report-editor-fit-plot");figure.dataset.reportFitPlot="true";figure.contentEditable="false";const img=element("img");img.src=block.data_url||"";img.alt=block.caption||"拟合结果图";figure.appendChild(img);if(block.caption)figure.appendChild(element("figcaption","",block.caption));return figure}
    return element("p","","");
  };
  const sectionById=id=>model.sections.find(section=>section.id===id);
  const renderEditors=()=>{$$('[data-report-field]',root).forEach(field=>{const key=field.dataset.reportField;if(field.type==="checkbox")field.checked=Boolean(model[key]);else field.value=model[key]??"";field.disabled=locked});$$('[data-report-rich-section]',root).forEach(area=>{const section=sectionById(area.dataset.reportRichSection);area.textContent="";(section?.blocks||[]).forEach(block=>area.appendChild(editorBlock(block)));if(!area.childNodes.length)area.appendChild(element("p","",""))})};
  const marksFor=node=>{const marks=[],area=node.parentElement?.closest('[data-report-rich-section]');let current=node.parentElement;while(current&&current!==area){const tag=current.tagName;if(tag==="STRONG"||tag==="B")marks.push("bold");if(tag==="EM"||tag==="I")marks.push("italic");if(tag==="U")marks.push("underline");if(tag==="SUP")marks.push("superscript");if(tag==="SUB")marks.push("subscript");current=current.parentElement}return [...new Set(marks)]};
  const runsFrom=node=>{const runs=[];const walker=document.createTreeWalker(node,NodeFilter.SHOW_TEXT|NodeFilter.SHOW_ELEMENT);let current;while(current=walker.nextNode()){if(current.nodeType===Node.TEXT_NODE&&current.textContent){const marks=marksFor(current),previous=runs.at(-1);if(previous&&JSON.stringify(previous.marks)===JSON.stringify(marks))previous.text+=current.textContent;else runs.push({text:current.textContent,marks})}else if(current.nodeType===Node.ELEMENT_NODE&&current.tagName==="BR")runs.push({text:"\n",marks:[]})}return runs};
  const serializeTable=figure=>({type:"table",rows:$$('tr',figure).map(row=>$$('th,td',row).map(cell=>cell.textContent.trim())),caption:$('figcaption',figure)?.textContent.trim()||""});
  const serializeArea=area=>{
    const blocks=[];[...area.children].forEach(node=>{const tag=node.tagName;
      if(node.classList.contains("report-editor-formula")){blocks.push({type:"formula",latex:node.dataset.latex||node.textContent.trim(),caption:$("small",node)?.textContent.trim()||""});return}
      if(node.classList.contains("report-editor-image")){blocks.push({type:"image",asset_hash:node.dataset.assetHash,caption:$("figcaption",node)?.textContent.trim()||"",width:Number(node.dataset.width||80),alignment:node.dataset.alignment||"center"});return}
      if(node.dataset.reportFitPlot==="true")return;
      if(node.classList.contains("report-editor-table")){blocks.push(serializeTable(node));return}
      if(tag==="OL"||tag==="UL"){blocks.push({type:"list",ordered:tag==="OL",items:$$('li',node).map(item=>item.textContent.trim()).filter(Boolean)});return}
      const type=/^H[1-6]$/.test(tag)?"heading":tag==="BLOCKQUOTE"?"quote":"paragraph",runs=runsFrom(node),text=runs.map(run=>run.text).join("");if(text.trim()||type!=="paragraph")blocks.push({type,text,runs,alignment:node.style.textAlign||"justify"})
    });return blocks.length?blocks:[{type:"paragraph",text:"",runs:[]}]
  };
  const gather=()=>{
    $$('[data-report-field]',root).forEach(field=>{const key=field.dataset.reportField;model[key]=field.type==="checkbox"?field.checked:field.value.trim()});
    $$('[data-report-rich-section]',root).forEach(area=>{const section=sectionById(area.dataset.reportRichSection);if(section)section.blocks=serializeArea(area)});
    const fit=$("[data-fit-result]");if(fit?.value){try{model.fit_result=JSON.parse(fit.value)}catch{}}
    const raw=$("[data-fit-data]");if(raw?.value){const section=sectionById("raw_data"),rows=raw.value.split(/\n+/).filter(Boolean).map(row=>row.split(","));if(section&&rows.length){const table=section.blocks.find(block=>block.type==="table"&&(String(block.caption||"").includes("拟合输入")||String(block.caption||"").includes("原始测量数据")));if(table){table.rows=rows;table.caption="原始测量数据（拟合输入）"}else if(!section.blocks.some(block=>String(block.text||"").trim()||block.type==="table")){section.blocks=[{type:"table",rows,caption:"原始测量数据（拟合输入）"}]}}}
    return model
  };
  const previewBlock=block=>{const holder=element("div");if(["paragraph","heading","quote"].includes(block.type)){const node=element(block.type==="heading"?"h4":block.type==="quote"?"blockquote":"p");appendRuns(node,block);node.style.textAlign=block.alignment||"justify";holder.appendChild(node)}else if(block.type==="formula"){const node=element("div","academic-formula");renderFormula(node,block.latex);holder.appendChild(node);if(block.caption)holder.appendChild(element("small","academic-caption",block.caption))}else if(block.type==="list")holder.appendChild(editorBlock(block));else if(block.type==="table")holder.appendChild(editorBlock(block));else if(block.type==="image")holder.appendChild(editorBlock(block));else if(block.type==="fit_plot")holder.appendChild(editorBlock(block));return [...holder.childNodes]};
  const renderPaper=()=>{gather();paper.textContent="";const header=element("header","academic-running-head");header.append(element("span","",model.title_zh),element("span","","1"));paper.appendChild(header);paper.appendChild(element("h1","",model.title_zh));paper.appendChild(element("p","academic-author",`${model.author_name}  (${model.student_id})`));paper.appendChild(element("p","academic-affiliation",model.affiliation_zh));const zh=element("p","academic-abstract");zh.append(element("b","","摘要："),document.createTextNode(model.abstract_zh||""));paper.appendChild(zh);const kw=element("p","academic-keywords");kw.append(element("b","","关键词："),document.createTextNode(model.keywords_zh||""));paper.appendChild(kw);paper.appendChild(element("h2","academic-en-title",model.title_en));paper.appendChild(element("p","academic-author",`${model.author_name}  (${model.student_id})`));paper.appendChild(element("p","academic-affiliation",model.affiliation_en));const en=element("p","academic-abstract english");en.append(element("b","","Abstract: "),document.createTextNode(model.abstract_en||""));paper.appendChild(en);const ek=element("p","academic-keywords english");ek.append(element("b","","Keywords: "),document.createTextNode(model.keywords_en||""));paper.appendChild(ek);model.sections.forEach((section,index)=>{paper.appendChild(element("h3","",`${index+1}  ${section.title}`));section.blocks.forEach(block=>previewBlock(block).forEach(node=>paper.appendChild(node)));if(section.id==="fit"&&model.fit_result?.plot_data_url){previewBlock({type:"fit_plot",data_url:model.fit_result.plot_data_url,caption:"实验测量数据与拟合结果"}).forEach(node=>paper.appendChild(node))}})};
  const renderFitPlotInEditor=()=>{const area=$("[data-report-rich-section=\"fit\"]",root);if(!area)return;$("[data-report-fit-plot]",area)?.remove();if(model.fit_result?.plot_data_url){area.appendChild(editorBlock({type:"fit_plot",data_url:model.fit_result.plot_data_url,caption:"实验测量数据与拟合结果"}))}};
  const syncFitToReport=(markDirty=true)=>{const fit=$("[data-fit-result]");let changed=false;if(fit?.value){try{const next=JSON.parse(fit.value||"{}");if(JSON.stringify(model.fit_result||{})!==JSON.stringify(next)){model.fit_result=next;changed=true}}catch{}}const raw=$("[data-fit-data]"),section=sectionById("raw_data");if(raw?.value&&section){const rows=raw.value.split(/\n+/).filter(Boolean).map(row=>row.split(","));if(rows.length){let table=section.blocks.find(block=>block.type==="table"&&(String(block.caption||"").includes("拟合输入")||String(block.caption||"").includes("原始测量数据")));if(!table&&!section.blocks.some(block=>String(block.text||"").trim()||block.type==="table")){table={type:"table",rows:[],caption:"原始测量数据（拟合输入）"};section.blocks=[table];changed=true}if(table&&JSON.stringify(table.rows)!==JSON.stringify(rows)){table.rows=rows;table.caption="原始测量数据（拟合输入）";changed=true}}}renderEditors();renderFitPlotInEditor();if(changed&&markDirty)schedule();else renderPaper()};
  const schedule=()=>{if(locked||conflicted)return;dirty=true;setState("正在编辑…","editing");clearTimeout(saveTimer);saveTimer=setTimeout(save,1200);renderPaper()};
  async function save(){if(locked||conflicted||!dirty)return true;clearTimeout(saveTimer);dirty=false;setState("正在保存…","saving");const content=gather();savePromise=fetch(root.dataset.saveUrl,{method:"PUT",headers:csrfHeaders({"Content-Type":"application/json"}),body:JSON.stringify({lock_version:lockVersion,content})});try{const response=await savePromise,result=await response.json();if(response.status===409){conflicted=true;localStorage.setItem(storageKey,JSON.stringify(content));setState("其他页面已修改 · 本地内容已备份","conflict");if(confirm("其他页面已修改这份草稿。按“确定”加载服务器版本；按“取消”保留当前页面和本地备份。")){model=result.draft.content;lockVersion=result.draft.lock_version;conflicted=false;localStorage.removeItem(storageKey);renderEditors();renderPaper();setState("已加载服务器版本")}return false}if(!response.ok)throw new Error(result.error||"保存失败");lockVersion=result.lock_version;model=result.content;localStorage.removeItem(storageKey);setState(`已保存 ${new Date().toLocaleTimeString()}`,"saved");return true}catch(error){dirty=true;try{localStorage.setItem(storageKey,JSON.stringify(content))}catch{}setState(`保存失败：${error.message}`,"error");return false}finally{savePromise=null}}
  const activate=id=>{activeSection=id;$$('[data-report-section-target]',root).forEach(button=>button.classList.toggle("active",button.dataset.reportSectionTarget===id));$$('[data-report-edit-panel]',root).forEach(panel=>panel.classList.toggle("active",panel.dataset.reportEditPanel===id));$(`[data-report-rich-section="${id}"]`,root)?.focus()};
  $$('[data-report-section-target]',root).forEach(button=>button.addEventListener("click",()=>activate(button.dataset.reportSectionTarget)));
  root.addEventListener("input",event=>{if(event.target.closest('[data-report-field],[data-report-rich-section]'))schedule()});root.addEventListener("change",event=>{if(event.target.closest('[data-report-field]'))schedule()});
  $$('[data-rich-command]',root).forEach(button=>button.addEventListener("click",()=>{const area=$(`[data-report-rich-section="${activeSection}"]`,root)||$('[data-report-rich-section]',root);area?.focus();document.execCommand(button.dataset.richCommand,false);schedule()}));
  $("[data-report-insert-formula]",root)?.addEventListener("click",()=>{const latex=prompt("输入 LaTeX 公式，例如 u_0=p_1\\Omega^2+p_2");if(!latex)return;const area=$(`[data-report-rich-section="${activeSection}"]`,root);area?.appendChild(editorBlock({type:"formula",latex,caption:""}));schedule()});
  $("[data-report-insert-table]",root)?.addEventListener("click",()=>{const rows=Math.max(2,Math.min(20,Number(prompt("表格行数（含表头）","3"))||0)),cols=Math.max(2,Math.min(10,Number(prompt("表格列数","3"))||0));if(!rows||!cols)return;const values=Array.from({length:rows},(_,r)=>Array.from({length:cols},(_,c)=>r===0?`表头${c+1}`:""));$(`[data-report-rich-section="${activeSection}"]`,root)?.appendChild(editorBlock({type:"table",rows:values,caption:""}));schedule()});
  root.addEventListener("dblclick",event=>{const formula=event.target.closest(".report-editor-formula"),image=event.target.closest(".report-editor-image"),table=event.target.closest(".report-editor-table");if(formula){const oldCaption=$("small",formula)?.textContent||"",latex=prompt("修改 LaTeX 公式",formula.dataset.latex||"");if(latex!==null){formula.dataset.latex=latex;renderFormula(formula,latex);if(oldCaption)formula.appendChild(element("small","",oldCaption));schedule()}}else if(image){const caption=prompt("修改图注",$("figcaption",image)?.textContent||"")??"",width=Math.max(20,Math.min(100,Number(prompt("图片宽度百分比",image.dataset.width||"80"))||80)),alignment=prompt("对齐方式：left、center 或 right",image.dataset.alignment||"center");image.dataset.width=String(width);image.dataset.alignment=["left","center","right"].includes(alignment)?alignment:"center";$("img",image).style.width=`${width}%`;let cap=$("figcaption",image);if(caption&&!cap){cap=element("figcaption");image.appendChild(cap)}if(cap)cap.textContent=caption;schedule()}else if(table){const old=serializeTable(table),rowCount=Math.max(2,Math.min(60,Number(prompt("调整表格行数（含表头）",String(old.rows.length)))||old.rows.length)),colCount=Math.max(2,Math.min(12,Number(prompt("调整表格列数",String(old.rows[0]?.length||2)))||2)),rows=Array.from({length:rowCount},(_,r)=>Array.from({length:colCount},(_,c)=>old.rows[r]?.[c]??(r===0?`表头${c+1}`:"")));table.replaceWith(editorBlock({type:"table",rows,caption:old.caption}));schedule()}});
  const imageInput=$("[data-report-image-input]",root);$("[data-report-insert-image]",root)?.addEventListener("click",()=>imageInput?.click());imageInput?.addEventListener("change",async()=>{const file=imageInput.files[0];if(!file)return;setState("正在上传图片…","saving");const body=new FormData();body.append("image",file);try{const response=await fetch(root.dataset.imageUrl,{method:"POST",headers:csrfHeaders(),body}),result=await response.json();if(!response.ok)throw new Error(result.error||"上传失败");lockVersion=result.lock_version;const caption=prompt("图片说明（可稍后重新插入修改）",file.name)||"";$(`[data-report-rich-section="${activeSection}"]`,root)?.appendChild(editorBlock({type:"image",asset_hash:result.asset_hash,caption,width:80,alignment:"center"}));schedule()}catch(error){setState(error.message,"error")}finally{imageInput.value=""}});
  $("[data-report-translate]",root)?.addEventListener("click",async event=>{const button=event.currentTarget;gather();button.disabled=true;setState("AI 正在生成英文草稿…","saving");try{if(dirty&&!await save())return;const response=await fetch(root.dataset.translateUrl,{method:"POST",headers:csrfHeaders({"Content-Type":"application/json"}),body:JSON.stringify({lock_version:lockVersion,content:gather()})}),result=await response.json();if(!response.ok)throw new Error(result.error||"生成失败");model=result.content;lockVersion=result.lock_version;renderEditors();renderPaper();setState("英文草稿已生成，请检查并修改","saved")}catch(error){setState(error.message,"error")}finally{button.disabled=false}});
  $("[data-report-exact-preview]",root)?.addEventListener("click",async event=>{const button=event.currentTarget;button.disabled=true;setState("正在生成精确 PDF 预览…","saving");try{const response=await fetch(root.dataset.previewUrl,{method:"POST",headers:csrfHeaders({"Content-Type":"application/json"}),body:JSON.stringify({content:gather()})});if(!response.ok){const result=await response.json();throw new Error(result.error||"预览失败")}const url=URL.createObjectURL(await response.blob());window.open(url,"_blank","noopener");setTimeout(()=>URL.revokeObjectURL(url),60000);setState("精确 PDF 预览已生成","saved")}catch(error){setState(error.message,"error")}finally{button.disabled=false}});
  const submitForm=$("[data-submission-form]",root);submitForm?.addEventListener("submit",async event=>{if(submitting)return;event.preventDefault();gather();if(!model.steps_complete){setState("请先确认已完成全部必做步骤","error");return}if(!model.result_value){setState("请填写关键结果","error");return}dirty=true;if(!await save())return;submitting=true;submitForm.requestSubmit()});
  $("[data-report-mobile-toggle]",root)?.addEventListener("click",()=>root.classList.toggle("show-editor"));
  document.addEventListener("workspace:tab",event=>{if(event.detail.name==="report")syncFitToReport(true)});
  window.addEventListener("beforeunload",event=>{if(dirty){event.preventDefault();event.returnValue=""}});
  const fitImage=$("[data-fit-output] img");fitImage?.addEventListener("load",()=>syncFitToReport(true));
  renderEditors();syncFitToReport(false);activate("frontmatter");if(locked)setState("已随正式提交冻结","locked");
}

function setupReport(){const root=$("[data-report-viewer]");if(!root)return;const pages=$$("[data-report-page]",root),targets=$$("[data-report-target]",root),current=$("[data-report-current]",root);let index=0;const render=()=>{pages.forEach((page,i)=>page.classList.toggle("active",i===index));targets.forEach((button,i)=>button.classList.toggle("active",i===index));current.textContent=index+1};targets.forEach((button,i)=>button.addEventListener("click",()=>{index=i;render()}));$("[data-report-prev]",root).addEventListener("click",()=>{index=Math.max(0,index-1);render()});$("[data-report-next]",root).addEventListener("click",()=>{index=Math.min(pages.length-1,index+1);render()})}

function setupStudentAssistant(){
  const panel=$("[data-student-ai]"),launcher=$("[data-open-student-ai]"),close=$("[data-close-student-ai]"),form=$("[data-student-ai-form]"),question=$("[data-ai-question]"),messages=$("[data-ai-messages]");if(!panel||!launcher||!form)return;
  const history=[];
  const setOpen=open=>{panel.classList.toggle("open",open);panel.setAttribute("aria-hidden",String(!open));launcher.classList.toggle("is-hidden",open);if(open)setTimeout(()=>question.focus(),180)};
  const renderAssistantContent=value=>{const math=[];const tokenized=value.replace(/\$\$([\s\S]+?)\$\$|\\\[([\s\S]+?)\\\]|\\\(([\s\S]+?)\\\)|\$([^$\n]+?)\$/g,(match,blockA,blockB,inlineA,inlineB)=>{const source=blockA??blockB??inlineA??inlineB,display=blockA!==undefined||blockB!==undefined;let html;try{html=window.katex?window.katex.renderToString(source,{throwOnError:false,displayMode:display,strict:"ignore"}):`<code class="math-source">${escapeHtml(source)}</code>`}catch{html=`<code class="math-source">${escapeHtml(source)}</code>`}const token=`@@MATH${math.length}@@`;math.push(html);return token});const lines=escapeHtml(tokenized).split(/\n+/).filter(line=>line.trim()).map(line=>{const ordered=line.match(/^\s*(\d+)\.\s+(.+)/),bullet=line.match(/^\s*[-*]\s+(.+)/);if(ordered)return `<div class="ai-list-item"><span>${ordered[1]}.</span><p>${ordered[2]}</p></div>`;if(bullet)return `<div class="ai-list-item"><span>•</span><p>${bullet[1]}</p></div>`;return `<p>${line}</p>`});let html=lines.join("").replace(/\*\*(.+?)\*\*/g,"<strong>$1</strong>");math.forEach((rendered,index)=>{html=html.replace(`@@MATH${index}@@`,rendered)});return html};
  const addMessage=(role,content,waiting=false)=>{const bubble=document.createElement("div");bubble.className=`ai-bubble ${role}${waiting?" waiting":""}`;if(role==="assistant"&&!waiting){bubble.classList.add("ai-rendered");bubble.innerHTML=renderAssistantContent(content)}else{const p=document.createElement("p");p.textContent=content;bubble.appendChild(p)}messages.appendChild(bubble);messages.scrollTop=messages.scrollHeight;return bubble};
  const updateAssistant=(bubble,content,streaming=false)=>{bubble.classList.remove("waiting");bubble.classList.add("ai-rendered");bubble.classList.toggle("streaming",streaming);bubble.innerHTML=renderAssistantContent(content||"正在生成回答…");messages.scrollTop=messages.scrollHeight};
  const ask=async text=>{const clean=text.trim();if(!clean)return;addMessage("user",clean);history.push({role:"user",content:clean});question.value="";const waiting=addMessage("assistant","正在连接 AI 助教…",true);form.classList.add("busy");let answer="";try{const experimentCode=$("[data-experiment-code]")?.dataset.experimentCode||"";const response=await fetch(endpoint("studentAiUrl","/api/student/assistant"),{method:"POST",headers:csrfHeaders({"Content-Type":"application/json","Accept":"text/event-stream"}),body:JSON.stringify({question:clean,experiment_code:experimentCode,history:history.slice(-6,-1)})});const contentType=response.headers.get("content-type")||"";if(!contentType.includes("text/event-stream")){const result=await response.json();if(!response.ok)throw new Error(result.error||"答疑失败");answer=result.answer||"";updateAssistant(waiting,answer,false)}else{if(!response.ok||!response.body)throw new Error("AI 流式连接失败");const reader=response.body.getReader(),decoder=new TextDecoder();let buffer="",finished=false;while(!finished){const part=await reader.read();finished=part.done;buffer+=decoder.decode(part.value||new Uint8Array(),{stream:!finished});const blocks=buffer.split(/\r?\n\r?\n/);buffer=blocks.pop()||"";for(const block of blocks){for(const line of block.split(/\r?\n/)){if(!line.startsWith("data:"))continue;const event=JSON.parse(line.slice(5).trim());if(event.type==="delta"){answer+=event.content||"";updateAssistant(waiting,answer,true)}else if(event.type==="error")throw new Error(event.error||"答疑失败")}}}if(!answer)throw new Error("AI 未返回内容");updateAssistant(waiting,answer,false)}history.push({role:"assistant",content:answer})}catch(error){if(answer)updateAssistant(waiting,`${answer}\n\n[连接中断：${error.message}]`,false);else{waiting.remove();addMessage("assistant",error.message)}}finally{form.classList.remove("busy");question.focus()}};
  launcher.addEventListener("click",()=>setOpen(true));close.addEventListener("click",()=>setOpen(false));form.addEventListener("submit",event=>{event.preventDefault();if(!form.classList.contains("busy"))ask(question.value)});question.addEventListener("keydown",event=>{if(event.key==="Enter"&&!event.shiftKey){event.preventDefault();form.requestSubmit()}});$$("[data-ai-prompt]",panel).forEach(button=>button.addEventListener("click",()=>ask(button.dataset.aiPrompt)));document.addEventListener("keydown",event=>{if(event.key==="Escape"&&panel.classList.contains("open"))setOpen(false)});
}

function setupAmbient(){
  const root=$(".ambient-scene"),petals=$(".petal-field"),quantum=$(".quantum-field");if(!root||!petals||!quantum)return;
  const reduced=window.matchMedia("(prefers-reduced-motion: reduce)").matches,isTeacher=document.body.dataset.ambient==="teacher";
  for(let i=0;i<10;i++){const particle=document.createElement("i");particle.className="quantum-particle";particle.style.left=`${8+(i*23)%91}%`;particle.style.top=`${12+(i*37)%76}%`;particle.style.setProperty("--duration",`${12+(i%5)*3}s`);particle.style.animationDelay=`-${i*1.7}s`;quantum.appendChild(particle)}
  if(!reduced){const petalCount=isTeacher?24:46;for(let i=0;i<petalCount;i++){const petal=document.createElement("i"),drift=(i%2?1:-1)*(48+(i%6)*18);petal.className=`petal ${isTeacher?"teacher-petal":""}`;petal.style.setProperty("--x",`${2+(i*19)%97}%`);petal.style.setProperty("--size",`${8+(i%6)*3}px`);petal.style.setProperty("--duration",`${11+(i%8)*1.8}s`);petal.style.setProperty("--delay",`${-i*1.05}s`);petal.style.setProperty("--drift",`${drift}px`);petal.style.setProperty("--drift-end",`${Math.round(drift*-.58)}px`);petals.appendChild(petal)}}
  if(reduced)return;
  $$(".campus-illustration,.login-showcase").forEach(scene=>scene.addEventListener("pointermove",event=>{const rect=scene.getBoundingClientRect(),x=((event.clientX-rect.left)/rect.width-.5)*-10,y=((event.clientY-rect.top)/rect.height-.5)*-6;scene.style.setProperty("--px",`${x}px`);scene.style.setProperty("--py",`${y}px`)}));
}

function setupExperimentGallery(){
  const gallery=$("[data-experiment-gallery]"),previous=$("[data-gallery-prev]"),next=$("[data-gallery-next]");if(!gallery||!previous||!next)return;
  let frame;
  const update=()=>{const maximum=Math.max(0,gallery.scrollWidth-gallery.clientWidth),scrollable=maximum>4;previous.disabled=!scrollable||gallery.scrollLeft<=4;next.disabled=!scrollable||gallery.scrollLeft>=maximum-4;gallery.classList.toggle("is-scrollable",scrollable)};
  const scheduleUpdate=()=>{cancelAnimationFrame(frame);frame=requestAnimationFrame(update)};
  const distance=()=>Math.max(280,Math.min(gallery.clientWidth*.82,720));
  previous.addEventListener("click",()=>gallery.scrollBy({left:-distance(),behavior:"smooth"}));
  next.addEventListener("click",()=>gallery.scrollBy({left:distance(),behavior:"smooth"}));
  gallery.addEventListener("scroll",scheduleUpdate,{passive:true});
  gallery.addEventListener("keydown",event=>{if(event.key!=="ArrowLeft"&&event.key!=="ArrowRight")return;event.preventDefault();gallery.scrollBy({left:(event.key==="ArrowLeft"?-1:1)*distance(),behavior:"smooth"})});
  window.addEventListener("resize",scheduleUpdate,{passive:true});requestAnimationFrame(update);
}

function setupAchievements(){
  const root=$("[data-achievement-gallery]");if(!root)return;
  const items=$$("[data-achievement-item]",root),certificate=$("[data-achievement-certificate]",root),title=$("[data-certificate-title]",root),message=$("[data-certificate-message]",root),status=$("[data-certificate-status]",root),dialog=$("[data-achievement-dialog]"),dialogTitle=$("[data-achievement-dialog-title]",dialog),dialogSummary=$("[data-achievement-dialog-summary]",dialog),dialogDescription=$("[data-achievement-dialog-description]",dialog),dialogStatus=$("[data-achievement-dialog-status]",dialog),dialogRecord=$("[data-achievement-dialog-record]",dialog);
  const chime=()=>{try{const Audio=window.AudioContext||window.webkitAudioContext;if(!Audio)return;const audio=new Audio(),gain=audio.createGain();gain.connect(audio.destination);gain.gain.setValueAtTime(.0001,audio.currentTime);gain.gain.exponentialRampToValueAtTime(.055,audio.currentTime+.02);gain.gain.exponentialRampToValueAtTime(.0001,audio.currentTime+.55);[523.25,659.25,783.99].forEach((frequency,index)=>{const oscillator=audio.createOscillator();oscillator.type="sine";oscillator.frequency.value=frequency;oscillator.connect(gain);oscillator.start(audio.currentTime+index*.08);oscillator.stop(audio.currentTime+.62)});setTimeout(()=>audio.close(),900)}catch{}}
  const selectItem=item=>{const unlocked=item.dataset.unlocked==="true";items.forEach(entry=>entry.classList.toggle("active",entry===item));certificate.classList.toggle("is-unlocked",unlocked);certificate.classList.toggle("is-locked",!unlocked);title.textContent=item.dataset.title;message.textContent=unlocked?"已完成全部实验流程并正式提交报告":"完成全部实验流程并正式提交报告后解锁";status.textContent=unlocked?"已解锁":"待完成";status.classList.toggle("unlocked",unlocked);status.classList.toggle("locked",!unlocked)};
  const showDetail=item=>{const unlocked=item.dataset.unlocked==="true";selectItem(item);dialogTitle.textContent=item.dataset.title;dialogSummary.textContent=item.dataset.summary;dialogDescription.textContent=item.dataset.description;dialogStatus.textContent=unlocked?"纪念证书已解锁":"纪念证书待完成";dialogRecord.textContent=unlocked?`报告 R${item.dataset.revision} · ${item.dataset.unlockedAt} 解锁`:"尚未提交正式报告";openModal("achievement-detail");if(unlocked)chime()};
  items.forEach(item=>item.addEventListener("click",()=>showDetail(item)));
  $("[data-achievement-dialog-close]",dialog)?.addEventListener("click",()=>closeModal(dialog));
  const storageKey=`learningMemorial:${root.dataset.achievementOwner}`,unlockedCodes=(root.dataset.unlockedCodes||"").split(",").filter(Boolean);let seen=[];try{seen=JSON.parse(localStorage.getItem(storageKey)||"[]")}catch{}
  const newlyUnlocked=unlockedCodes.find(code=>!seen.includes(code));try{localStorage.setItem(storageKey,JSON.stringify(unlockedCodes))}catch{}
  if(newlyUnlocked){const item=items.find(entry=>entry.dataset.code===newlyUnlocked);if(item){item.classList.add("is-newly-unlocked");setTimeout(()=>{selectItem(item);item.scrollIntoView({behavior:window.matchMedia("(prefers-reduced-motion: reduce)").matches?"auto":"smooth",block:"nearest",inline:"center"})},500)}}
}

function renderTeacherAiContent(value){
  return escapeHtml(value).split(/\n+/).filter(Boolean).map(line=>{
    const heading=line.match(/^#{1,3}\s+(.+)/),bullet=line.match(/^\s*[-*]\s+(.+)/),ordered=line.match(/^\s*(\d+)\.\s+(.+)/);
    if(heading)return `<h3>${heading[1]}</h3>`;
    if(bullet)return `<div class="ai-list-item"><span>•</span><p>${bullet[1]}</p></div>`;
    if(ordered)return `<div class="ai-list-item"><span>${ordered[1]}.</span><p>${ordered[2]}</p></div>`;
    return `<p>${line}</p>`;
  }).join("").replace(/\*\*(.+?)\*\*/g,"<strong>$1</strong>");
}

function setupTeacherAssistant(){
  const panel=$("[data-teacher-ai]"),launcher=$("[data-teacher-ai-launcher]"),form=$("[data-teacher-ai-form]"),question=$("[data-teacher-ai-question]"),messages=$("[data-teacher-ai-messages]"),course=$("[data-teacher-ai-course]"),sync=$("[data-teacher-ai-sync]");
  if(!panel||!form||!question||!messages)return;
  let loaded=false,busy=false;
  const setOpen=open=>{panel.classList.toggle("open",open);panel.setAttribute("aria-hidden",String(!open));launcher?.classList.toggle("is-hidden",open);if(open){loadCourses();setTimeout(()=>question.focus(),120)}};
  const addMessage=(role,content,waiting=false)=>{const bubble=document.createElement("div");bubble.className=`ai-bubble ${role}${waiting?" waiting":" ai-rendered"}`;if(role==="assistant"&&!waiting)bubble.innerHTML=renderTeacherAiContent(content);else{const p=document.createElement("p");p.textContent=content;bubble.appendChild(p)}messages.appendChild(bubble);messages.scrollTop=messages.scrollHeight;return bubble};
  const loadCourses=async()=>{if(loaded)return;loaded=true;try{const response=await fetch(endpoint("teacherAnalyticsUrl","/api/teacher/analytics"));const payload=await response.json();if(!response.ok)throw new Error(payload.error||"课程读取失败");course.innerHTML=(payload.courses||[]).map(item=>`<option value="${escapeHtml(item.id)}">${escapeHtml(item.name)}</option>`).join("")||'<option value="">暂无课程</option>';if(payload.course?.id)course.value=payload.course.id;if(sync)sync.textContent=`数据同步：${new Date(payload.generated_at).toLocaleString()}`}catch(error){if(sync)sync.textContent=error.message}};
  const ask=async text=>{const clean=text.trim();if(!clean||busy)return;busy=true;addMessage("user",clean);question.value="";const waiting=addMessage("assistant","正在读取服务器学情快照…",true);form.classList.add("busy");try{const response=await fetch(endpoint("teacherAiUrl","/api/teacher/assistant"),{method:"POST",headers:csrfHeaders({"Content-Type":"application/json"}),body:JSON.stringify({question:clean,course_id:course.value||null})});const result=await response.json();if(!response.ok)throw new Error(result.error||"AI 学情分析失败");waiting.remove();addMessage("assistant",result.answer);if(sync)sync.textContent=`数据同步：${new Date().toLocaleString()}`}catch(error){waiting.remove();addMessage("assistant",error.message)}finally{busy=false;form.classList.remove("busy");question.focus()}};
  $$('[data-open-teacher-ai]').forEach(button=>button.addEventListener("click",()=>setOpen(true)));
  $("[data-close-teacher-ai]")?.addEventListener("click",()=>setOpen(false));
  $$('[data-teacher-ai-prompt]',panel).forEach(button=>button.addEventListener("click",()=>ask(button.dataset.teacherAiPrompt)));
  form.addEventListener("submit",event=>{event.preventDefault();ask(question.value)});
  question.addEventListener("keydown",event=>{if(event.key==="Enter"&&!event.shiftKey){event.preventDefault();form.requestSubmit()}});
  document.addEventListener("keydown",event=>{if(event.key==="Escape"&&panel.classList.contains("open"))setOpen(false)});
}

function setupTeacherAnalytics(){
  const root=$("[data-teacher-analytics]");if(!root)return;
  const form=$("[data-analytics-filters]",root),sync=$("[data-analytics-sync]",root),studentBody=$("[data-student-details]",root),experimentBody=$("[data-experiment-stats]",root),slowest=$("[data-slowest-students]",root),search=$("[data-student-search]",root),filterToggle=$("[data-analytics-filter-toggle]",root),statusFilters=$$("[data-student-status-filter]",root);
  let activeStudentFilter="all";
  const query=()=>form?new URLSearchParams(new FormData(form)).toString():"";
  const apiUrl=()=>`${root.dataset.apiUrl||endpoint("teacherAnalyticsUrl","/api/teacher/analytics")}${query()?`?${query()}`:""}`;
  const setMetric=(name,value)=>{const el=$(`[data-metric="${name}"]`,root);if(el)el.textContent=value};
  const display=value=>value===null||value===undefined?"—":value;
  const shortTime=value=>value?String(value).slice(5,16).replace("T"," "):"—";
  const filterStudentRows=()=>{const value=search?.value.trim().toLowerCase()||"";$$('[data-student-id]',studentBody).forEach(row=>{const matchesText=!value||row.dataset.studentQuery.toLowerCase().includes(value),matchesStatus=activeStudentFilter==="all"||(activeStudentFilter==="incomplete"&&row.dataset.studentIncomplete==="true")||(activeStudentFilter==="warning"&&row.dataset.studentWarning==="true");row.hidden=!(matchesText&&matchesStatus)})};
  const renderStudents=rows=>{if(!studentBody)return;studentBody.innerHTML=(rows||[]).map(student=>`<tr id="student-${escapeHtml(student.id)}" data-student-id="${escapeHtml(student.id)}" data-student-query="${escapeHtml(`${student.name} ${student.username}`)}" data-student-incomplete="${student.completion_rate<100}" data-student-warning="${Boolean(student.warning)}" class="${student.warning?"is-warning":""}"><td data-label="学生"><b>${escapeHtml(student.name)}</b><small>${escapeHtml(student.username)}</small></td><td class="teacher-number" data-label="任务状态">${student.completed} 完成 · ${student.in_progress} 进行中 · ${student.not_started} 未开始</td><td class="teacher-number" data-label="整体进度"><span class="student-progress"><i style="width:${student.completion_rate}%"></i></span><b>${student.completion_rate}%</b></td><td class="teacher-number" data-label="预习均分">${display(student.quiz_average)}</td><td class="teacher-number" data-label="教师评分均分">${display(student.teacher_score_average)}</td><td class="teacher-number" data-label="最近活动">${shortTime(student.latest_activity_at)}<small>${student.inactive_days===null?"尚未开始":`${student.inactive_days} 天前`}</small></td><td data-label="预警">${student.warning?`<span class="analytics-warning"><i data-lucide="triangle-alert"></i>${escapeHtml(student.warning_reason)}</span>`:'<span class="status published">正常</span>'}</td></tr>`).join("")||'<tr><td class="empty-table" colspan="7">当前筛选范围暂无学生</td></tr>';filterStudentRows();refreshIcons()};
  const renderExperiments=rows=>{if(!experimentBody)return;experimentBody.innerHTML=(rows||[]).map(item=>`<tr><td data-label="实验项目"><b>${escapeHtml(item.experiment)}</b><small>${escapeHtml(item.experiment_code)}</small></td><td class="teacher-number" data-label="预习完成率"><span class="inline-rate"><i style="width:${item.prestudy_rate||0}%"></i></span><b>${item.prestudy_rate===null?"—":`${item.prestudy_rate}%`}</b></td><td class="teacher-number" data-label="报告完成率"><span class="inline-rate report"><i style="width:${item.report_rate||0}%"></i></span><b>${item.report_rate===null?"—":`${item.report_rate}%`}</b></td><td class="teacher-number" data-label="预习均分">${display(item.quiz_average)}</td><td class="teacher-number" data-label="教师评分均分">${display(item.teacher_score_average)}</td><td data-label="待审核"><span class="status ${item.pending_reviews?"draft":"published"} teacher-number">${item.pending_reviews}</span></td><td class="teacher-number" data-label="最近提交">${shortTime(item.latest_submission_at)}</td></tr>`).join("")||'<tr><td class="empty-table" colspan="7">当前筛选范围暂无实验任务</td></tr>'};
  const renderSlowest=rows=>{if(!slowest)return;slowest.innerHTML=(rows||[]).map((student,index)=>`<button type="button" data-student-drill="${escapeHtml(student.id)}"><span class="teacher-number">${index+1}</span><div><b>${escapeHtml(student.name)}</b><small>${escapeHtml(student.username)} · ${escapeHtml(student.warning_reason||"仍在推进")}</small></div><strong class="teacher-number">${student.completion_rate}%</strong></button>`).join("")||'<p class="empty-copy">当前班级暂无学生</p>'};
  const apply=next=>{const summary=next.summary||{};setMetric("completion_rate",`${summary.completion_rate??0}%`);setMetric("quiz_average",display(summary.quiz_average));setMetric("teacher_score_average",display(summary.teacher_score_average));setMetric("warning_count",summary.warning_count??0);const context=$("[data-assignment-context]",root);if(context)context.textContent=`${summary.task_count??0} 项任务 × ${summary.student_count??0} 名学生`;const scope=$("[data-scope-name]",root);if(scope)scope.textContent=next.course?.name||"暂无班级";renderStudents(next.students);renderExperiments(next.experiment_stats);renderSlowest(next.slowest_students);if(sync)sync.textContent=`已刷新：${new Date(next.generated_at).toLocaleTimeString()}`};
  const refresh=async()=>{try{if(sync)sync.textContent="正在刷新…";const response=await fetch(apiUrl());const next=await response.json();if(!response.ok)throw new Error(next.error||"刷新失败");apply(next)}catch(error){if(sync)sync.textContent=error.message}};
  $("[data-analytics-refresh]",root)?.addEventListener("click",refresh);
  filterToggle?.addEventListener("click",()=>{const open=form.classList.toggle("is-open");filterToggle.setAttribute("aria-expanded",String(open))});
  root.addEventListener("click",event=>{const trigger=event.target.closest("[data-student-drill]");if(!trigger)return;const row=document.getElementById(`student-${CSS.escape(trigger.dataset.studentDrill)}`);if(!row)return;row.scrollIntoView({behavior:window.matchMedia("(prefers-reduced-motion: reduce)").matches?"auto":"smooth",block:"center"});row.classList.remove("is-drilled");requestAnimationFrame(()=>row.classList.add("is-drilled"))});
  search?.addEventListener("input",filterStudentRows);
  statusFilters.forEach(button=>button.addEventListener("click",()=>{activeStudentFilter=button.dataset.studentStatusFilter;statusFilters.forEach(item=>item.classList.toggle("active",item===button));filterStudentRows()}));
  setInterval(refresh,30000);
}

function showConfirm(form,message,submitter){
  const modal=document.createElement("div");modal.className="modal-backdrop";modal.innerHTML=`<section class="dialog-card" role="dialog" aria-modal="true"><button class="modal-close" data-cancel-confirm aria-label="关闭"><i data-lucide="x"></i></button><span class="eyebrow">CONFIRM ACTION</span><h2>确认当前操作</h2><p>${message}</p><div class="button-row"><button class="secondary-button" type="button" data-cancel-confirm>取消</button><button class="danger-button" type="button" data-accept-confirm>确认继续</button></div></section>`;document.body.appendChild(modal);document.body.style.overflow="hidden";refreshIcons();modal.addEventListener("click",event=>{if(event.target.closest("[data-cancel-confirm]")){modal.remove();document.body.style.overflow=""}if(event.target.closest("[data-accept-confirm]")){modal.remove();document.body.style.overflow="";form.dataset.confirmed="true";form.requestSubmit(submitter)}})
}

document.addEventListener("click",event=>{
  const confirmSubmit=event.target.closest("[data-confirm-submit]");if(confirmSubmit){event.preventDefault();showConfirm(confirmSubmit.form,confirmSubmit.dataset.confirmSubmit,confirmSubmit);return}
  const open=event.target.closest("[data-open-modal]");if(open){event.preventDefault();openModal(open.dataset.openModal)}
  const close=event.target.closest("[data-close-modal]");if(close){event.preventDefault();closeModal(close.closest(".modal-backdrop"))}
  const tab=event.target.closest("[data-tab-target]");if(tab)activateTab(tab.dataset.tabTarget);
  const jump=event.target.closest("[data-jump-tab]");if(jump){event.preventDefault();activateTab(jump.dataset.jumpTab)}
});
document.addEventListener("submit",event=>{const message=event.target.dataset.confirm;if(message&&!event.target.dataset.confirmed){event.preventDefault();showConfirm(event.target,message)}});
document.addEventListener("keydown",event=>{if(event.key==="Escape")closeModal(document.querySelector(".modal-backdrop:not(.is-hidden)"))});

document.addEventListener("DOMContentLoaded",()=>{
  setupAmbient();setupExperimentGallery();setupAchievements();setupAutoOpenModal();setupWorkspaceStepNavigation();setupStudentRecords();setupQuiz();setupFit();setupFilters();setupExperimentDraftAssistant();setupEditor();setupQuestionManager();setupReportEditor();setupReport();setupPrincipleFormula();setupAcademicFormulas();setupStudentAssistant();setupTeacherAssistant();setupTeacherAnalytics();refreshIcons();
  setTimeout(()=>$$('.flash').forEach(item=>item.remove()),5000);
});
