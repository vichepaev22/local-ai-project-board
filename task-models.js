/* Model labels and a local picker. Reading the catalog never dispatches work. */
const TaskModels = (() => {
  function label(item) { return item.model ? item.modelLabel || item.model : 'Как в задаче'; }
  function options(models, value) {
    const rows = [{value:'', label:'Как в задаче'}].concat(models.map(m=>({value:m.id,label:m.label})));
    if (value && !rows.some(row=>row.value===value)) rows.push({value,label:`${value} · нет в списке`,unavailable:true});
    return rows;
  }
  function create({select, status, reload, fetchModels, onChange}) {
    let models = [], pending = null, loading = false, error = '', loaded = false;
    function feedback() {
      const value=select.value, known=models.some(m=>m.id===value);
      const invalid=value && (loading || error || !loaded || !known);
      select.setCustomValidity(invalid ? 'Обновите список и выберите доступную модель или «Как в задаче».' : '');
      select.setAttribute('aria-invalid', invalid ? 'true' : 'false');
      status.textContent = loading ? 'Читаем модели настроенного исполнителя…' : error ? `${error} Выбор сохранён. Можно обновить список или выбрать «Как в задаче».` : value && !known ? 'Сохранённой модели нет в списке. Выберите другую — автоматической замены не будет.' : value ? 'Эта модель будет передана исполнителю после подтверждения запуска.' : 'Модель связанной задачи или локальные настройки исполнителя по умолчанию. Ручной режим не вызывает модель.';
      reload.disabled=loading;
    }
    function setValue(value='') {
      const selected=typeof value==='string'?value:'';
      select.replaceChildren(...options(models,selected).map(row=>{
        const option=document.createElement('option');option.value=row.value;option.textContent=row.label;return option;
      }));
      select.value=selected;feedback();
    }
    function load() {
      if(pending)return pending;
      loading=true;error='';feedback();
      pending=(async()=>{
        try {const data=await fetchModels();models=data.models;loaded=true;}
        catch(e){error=e.message || 'Список моделей недоступен.';}
        finally {loading=false;pending=null;setValue(select.value);}
      })();
      return pending;
    }
    select.addEventListener('change',()=>{feedback();onChange();});
    reload.addEventListener('click',load);
    return {setValue,load};
  }
  return {options,label,create};
})();
if(typeof module!=='undefined')module.exports=TaskModels;
