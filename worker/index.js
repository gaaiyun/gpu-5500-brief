const json = (value,status=200) => new Response(JSON.stringify(value),{status,headers:{'content-type':'application/json; charset=utf-8','cache-control':'no-store'}});
export default {
  async fetch(request,env) {
    const url=new URL(request.url);
    if(url.pathname==='/health')return json({ok:true,ai:Boolean(env.AI),model:'@cf/zai-org/glm-4.7-flash'});
    if(url.pathname!=='/summarize'||request.method!=='POST')return json({error:'not_found'},404);
    if(!env.INGEST_TOKEN||request.headers.get('authorization')!==`Bearer ${env.INGEST_TOKEN}`)return json({error:'unauthorized'},401);
    const raw=await request.text();
    if(raw.length>50000)return json({error:'input_too_large'},413);
    let body;try{body=JSON.parse(raw);}catch{return json({error:'invalid_json'},400);}
    if(typeof body.prompt!=='string'||!Array.isArray(body.sources)||body.sources.length>8)return json({error:'invalid_input'},400);
    const model='@cf/zai-org/glm-4.7-flash';
    try {
      const result=await env.AI.run(model,{messages:[{role:'system',content:body.prompt},{role:'user',content:JSON.stringify({sources:body.sources})}],temperature:.1,max_completion_tokens:6000,response_format:{type:'json_object'},chat_template_kwargs:{enable_thinking:false}});
      const text=result?.choices?.[0]?.message?.content ?? result?.response;
      if(typeof text!=='string'||!text.trim())return json({error:'empty_model_response'},502);
      const finish_reason=result?.choices?.[0]?.finish_reason;
      if(finish_reason==='length')return json({error:'model_output_truncated'},502);
      return json({model,text,finish_reason,generated_at:new Date().toISOString()});
    } catch(error) { return json({error:String(error?.message||error).slice(0,200)},502); }
  },
  // GitHub starts scheduled workflows hours late; this cron dispatches the 00:35 run on time.
  // The workflow's push log keeps each channel to one message a day, so GitHub's own late run only refreshes the site.
  async scheduled(controller,env) {
    if(!env.GH_DISPATCH_TOKEN){console.log('GH_DISPATCH_TOKEN not set; dispatch skipped');return;}
    let last='';
    for(let attempt=1;attempt<=3;attempt++){
      const response=await fetch('https://api.github.com/repos/gaaiyun/gpu-5500-brief/actions/workflows/daily.yml/dispatches',{method:'POST',
        headers:{authorization:`Bearer ${env.GH_DISPATCH_TOKEN}`,accept:'application/vnd.github+json','x-github-api-version':'2022-11-28','user-agent':'gpu-5500-brief-cron'},
        body:JSON.stringify({ref:'main',inputs:{scheduled:'true'}})});
      if(response.status===204){console.log(`dispatched daily run (attempt ${attempt})`);return;}
      last=`${response.status} ${(await response.text()).slice(0,200)}`;
      if(attempt<3)await new Promise(resolve=>setTimeout(resolve,20000));
    }
    throw new Error(`dispatch failed: ${last}`);
  }
};
