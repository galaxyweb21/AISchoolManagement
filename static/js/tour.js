/* EduAI Product Guide v7 - exact menu targeting, no coordinate overlay */
(function (window, document) {
  'use strict';

  var VERSION = '7.0';
  var role = ((document.body && document.body.getAttribute('data-eduai-role')) || 'USER').toUpperCase();
  var roleNames = {SUPER_ADMIN:'Super Admin', SCHOOL_ADMIN:'School Admin', TEACHER:'Teacher', PARENT:'Parent', STUDENT:'Student', BURSAR:'Bursar', HOD:'HOD', SECRETARY:'Secretary', REGISTRAR:'Registrar'};
  var routes = window.EDUAI_TOUR_ROUTES || {};
  var state = { index:-1, steps:[], mode:'tour', workflow:'', ui:null, target:null };
  var storageKey = 'eduai_product_guide_completed_' + role;

  var TARGETS = {
    dashboard:'[data-guide-target="dashboard"]', students:'[data-guide-target="students"]', attendance:'[data-guide-target="attendance"]',
    'grade-entry':'[data-guide-target="grade-entry"]', 'terminal-results':'[data-guide-target="terminal-results"]',
    billing:'[data-guide-target="billing"]', 'fee-preparation':'[data-guide-target="fee-preparation"]', 'student-fees':'[data-guide-target="student-fees"]',
    invoices:'[data-guide-target="invoices"]', notifications:'[data-guide-target="notifications"]', copilot:'[data-guide-target="copilot"]',
    'activity-log':'[data-guide-target="activity-log"]', 'product-guide':'[data-guide-target="product-guide"]'
  };

  function qs(selector){ if(!selector) return null; try{return document.querySelector(selector);}catch(e){return null;} }
  function qsv(selector){
    if(!selector) return null;
    try{
      var nodes=document.querySelectorAll(selector);
      for(var i=0;i<nodes.length;i++){
        var n=nodes[i], r=n.getBoundingClientRect();
        if(r.width>0 && r.height>0 && window.getComputedStyle(n).visibility!=='hidden' && window.getComputedStyle(n).display!=='none') return n;
      }
    }catch(e){}
    return null;
  }
  function route(name){ return routes[name] || null; }
  function targetFor(step){
    if(!step) return null;
    if(step.target && TARGETS[step.target]) return qsv(TARGETS[step.target]);
    if(step.targetId) return document.getElementById(step.targetId);
    return qs(step.selector);
  }
  function urlWithState(url, workflow, step){
    if(!url) return null;
    var join=url.indexOf('?')>=0?'&':'?';
    return url+join+'eduai_workflow='+encodeURIComponent(workflow)+'&eduai_step='+step;
  }

  var roleGuides={
    SUPER_ADMIN:[
      {title:'Welcome to EduAI',text:'This guide highlights the main areas available to Super Admins.',target:null},
      {title:'Dashboard',text:'Review the school overview, alerts, shortcuts and administrative metrics.',target:'dashboard'},
      {title:'Students',text:'Manage learner records and enrollment.',target:'students'},
      {title:'Attendance',text:'Monitor school attendance and daily records.',target:'attendance'},
      {title:'Academic Results',text:'Enter and review academic results and terminal reports.',target:'grade-entry'},
      {title:'Finance',text:'Manage fees, billing, invoices and collections.',target:'billing'},
      {title:'Notifications',text:'Manage announcements and review system notifications.',target:'notifications'},
      {title:'AI Copilot',text:'Ask questions about school data and operational tasks.',target:'copilot'},
      {title:'Activity Log',text:'Review audit activity and user actions.',target:'activity-log'},
      {title:'Ready to explore',text:'Your Super Admin guide is complete. Use Product Guide again whenever you need a walkthrough.',target:null}
    ],
    SCHOOL_ADMIN:[
      {title:'Welcome to EduAI',text:'This guide highlights the main areas available to School Admins.',target:null},
      {title:'Dashboard',text:'Review school operations and administrative alerts.',target:'dashboard'},
      {title:'Students',text:'Manage learner records and enrollment.',target:'students'},
      {title:'Attendance',text:'Monitor attendance records and school activity.',target:'attendance'},
      {title:'Academic Results',text:'Manage grade entry and terminal results.',target:'grade-entry'},
      {title:'Finance',text:'Review fees, billing, invoices and balances.',target:'billing'},
      {title:'Notifications',text:'Manage school announcements and notifications.',target:'notifications'},
      {title:'AI Copilot',text:'Use Copilot for school-data and operational questions.',target:'copilot'},
      {title:'Ready to explore',text:'Your School Admin guide is complete.',target:null}
    ],
    BURSAR:[
      {title:'Welcome to EduAI',text:'This guide highlights the finance workspace available to Bursars.',target:null},
      {title:'Dashboard',text:'Review finance-focused school information and alerts.',target:'dashboard'},
      {title:'Finance',text:'Open Billing Dashboard to work with fees, invoices, payments and balances.',target:'billing'},
      {title:'Fee Preparation',text:'Prepare and review class fees before billing.',target:'fee-preparation'},
      {title:'Student Fees',text:'Review prepared fees and outstanding amounts.',target:'student-fees'},
      {title:'Invoices',text:'Review invoices and payment records.',target:'invoices'},
      {title:'Notifications',text:'Review finance and school notifications.',target:'notifications'},
      {title:'AI Copilot',text:'Ask Copilot for finance and operational information available to your role.',target:'copilot'},
      {title:'Ready to explore',text:'Your Bursar guide is complete.',target:null}
    ],
    REGISTRAR:[
      {title:'Welcome to EduAI',text:'This guide highlights the learner-record and administration areas available to Registrars.',target:null},
      {title:'Dashboard',text:'Review your school overview and alerts.',target:'dashboard'},
      {title:'Students',text:'Create, update and review learner records according to your permissions.',target:'students'},
      {title:'Attendance',text:'Review attendance information relevant to your role.',target:'attendance'},
      {title:'Notifications',text:'Read school announcements and system notifications.',target:'notifications'},
      {title:'AI Copilot',text:'Ask Copilot for permitted school-data and operational information.',target:'copilot'},
      {title:'Ready to explore',text:'Your Registrar guide is complete.',target:null}
    ],
    SECRETARY:[
      {title:'Welcome to EduAI',text:'This guide highlights the administration and communication areas available to Secretaries.',target:null},
      {title:'Dashboard',text:'Review your school overview and alerts.',target:'dashboard'},
      {title:'Students',text:'Access learner information required for your administrative work.',target:'students'},
      {title:'Attendance',text:'Review attendance information available to your role.',target:'attendance'},
      {title:'Notifications',text:'Stay informed about announcements and school updates.',target:'notifications'},
      {title:'AI Copilot',text:'Use Copilot for permitted school-data and operational assistance.',target:'copilot'},
      {title:'Ready to explore',text:'Your Secretary guide is complete.',target:null}
    ],
    HOD:[
      {title:'Welcome to EduAI',text:'This guide highlights the academic and teaching areas available to Heads of Department.',target:null},
      {title:'Dashboard',text:'Review your academic overview and alerts.',target:'dashboard'},
      {title:'Students',text:'Review learner information relevant to your department.',target:'students'},
      {title:'Attendance',text:'Monitor attendance for the classes available to your role.',target:'attendance'},
      {title:'Grade Entry',text:'Enter and review academic results for your assigned work.',target:'grade-entry'},
      {title:'Terminal Results',text:'Review final results and report-card information.',target:'terminal-results'},
      {title:'Notifications',text:'Read school announcements and academic notifications.',target:'notifications'},
      {title:'AI Copilot',text:'Ask Copilot for permitted academic and operational information.',target:'copilot'},
      {title:'Ready to explore',text:'Your HOD guide is complete.',target:null}
    ],
    TEACHER:[
      {title:'Welcome to EduAI',text:'This guide highlights the teaching workspace available to Teachers.',target:null},
      {title:'Dashboard',text:'Review your teaching overview and important school activity.',target:'dashboard'},
      {title:'Students',text:'View learners relevant to your teaching work.',target:'students'},
      {title:'Attendance',text:'Record and review attendance for your assigned classes.',target:'attendance'},
      {title:'Grade Entry',text:'Enter continuous assessment and examination results.',target:'grade-entry'},
      {title:'Terminal Results',text:'Review final results and report-card information.',target:'terminal-results'},
      {title:'Notifications',text:'Read announcements and important school notifications.',target:'notifications'},
      {title:'AI Copilot',text:'Ask Copilot for permitted school-data and operational assistance.',target:'copilot'},
      {title:'Ready to explore',text:'Your Teacher guide is complete.',target:null}
    ],
    PARENT:[
      {title:'Welcome to EduAI',text:'This guide highlights the family features available to Parents.',target:null},
      {title:'Dashboard',text:'Review your family overview and key student information.',target:'dashboard'},
      {title:'Notifications',text:'Read attendance, fee, report-card, promotion and announcement notifications.',target:'notifications'},
      {title:'Ready to explore',text:'Use the Parent Portal pages available in your sidebar to review your children\'s information.',target:null}
    ],
    STUDENT:[
      {title:'Welcome to EduAI',text:'This guide highlights the student features available to you.',target:null},
      {title:'Dashboard',text:'Review your academic and school overview.',target:'dashboard'},
      {title:'Notifications',text:'Read announcements and important school updates.',target:'notifications'},
      {title:'Ready to explore',text:'Use your student pages to review attendance, grades and fees.',target:null}
    ]
  };

  var general=roleGuides[role]||[
    {title:'Welcome to EduAI',text:'This guide highlights the areas available to your account.',target:null},
    {title:'Dashboard',text:'Start here to review your school overview.',target:'dashboard'},
    {title:'Notifications',text:'Review messages and important system updates.',target:'notifications'},
    {title:'Ready to explore',text:'Use the pages available in your sidebar for your role.',target:null}
  ];

  var workflows={
    enrollment:{label:'How to enroll a student',icon:'bi-person-plus',steps:[
      {title:'Open Students',text:'Open the Students menu. This is where learner enrollment begins.',route:'students',target:'students'},
      {title:'Choose Add Student',text:'On the Students page, use the Add Student button to open the enrollment form.',route:'students',selector:'#eduaiAddStudentBtn, a[href*="create_student"], a[href*="student_create"]'},
      {title:'Complete the record',text:'Enter the required learner details and save the student record.',route:'student_create',selector:'form'},
      {title:'Verify the learner',text:'Confirm that the new learner appears in the student register.',route:'students',selector:'#studentsTable, table, .student-list'}
    ]},
    fees:{label:'How to prepare fees',icon:'bi-clipboard-check',steps:[
      {title:'Open Fee Preparation',text:'Open Fee Preparation from the Finance section.',route:'fee_preparation',target:'fee-preparation'},
      {title:'Select the term',text:'Choose the academic term for the fee preparation operation.',route:'fee_preparation',selector:'#term, select[name*="term"]'},
      {title:'Select the class',text:'Choose the class you want to prepare fees for.',route:'fee_preparation',selector:'#school-class, select[name*="class"]'},
      {title:'Prepare the fees',text:'Use the page action to prepare the selected class fees.',route:'fee_preparation',selector:'#prepare-class-btn, button[id*="prepare"], button[name*="prepare"]'},
      {title:'Verify preparation',text:'Review the preparation results or status on the page.',route:'fee_preparation',selector:'#feePrepTable, table'}
    ]},
    payment:{label:'How to record a payment',icon:'bi-cash-coin',steps:[
      {title:'Open Billing Dashboard',text:'Open Billing Dashboard to work with outstanding invoices and payment actions.',route:'billing',target:'billing'},
      {title:'Find an invoice',text:'Locate the student invoice that has an outstanding balance.',route:'billing',selector:'table, #invoiceTable, .table-responsive'},
      {title:'Open Record Payment',text:'Use the Record Payment action for the selected invoice.',route:'billing',selector:'button[id*="payment"], a[href*="payment"], [data-bs-target*="payment"]'},
      {title:'Record the payment',text:'Enter the amount and payment details, then submit the payment. Your existing receipt workflow remains unchanged.',route:'billing',selector:'#paymentForm'},
      {title:'Verify the receipt',text:'A successful payment opens the receipt in a new browser tab and updates the outstanding balance.',route:'billing',selector:null}
    ]},
    results:{label:'How to enter results',icon:'bi-pencil-square',steps:[
      {title:'Open Grade Entry',text:'Open Grade Entry from the Academic section.',route:'grading',target:'grade-entry'},
      {title:'Choose the academic context',text:'Select the appropriate term, class and subject/context presented by the grading portal.',route:'grading',selector:'form, select'},
      {title:'Enter marks',text:'Enter the class and examination marks for the learners shown.',route:'grading',selector:'table, input'},
      {title:'Save results',text:'Save the entered results and verify the success message.',route:'grading',selector:'button[type="submit"], button[name*="save"]'},
      {title:'Review Terminal Results',text:'Use Terminal Results to review the saved results and report-card data.',route:'terminal_results',target:'terminal-results'}
    ]},
    attendance:{label:'How to manage attendance',icon:'bi-calendar-check',steps:[
      {title:'Open Attendance',text:'Open the Attendance menu.',route:'attendance',target:'attendance'},
      {title:'Choose the date/class',text:'Select the date and class available to your role.',route:'attendance',selector:'form, select'},
      {title:'Complete the roll call',text:'Record each learner as Present, Late or Absent as appropriate.',route:'attendance',selector:'table, input, select'},
      {title:'Save attendance',text:'Submit or save the register and check the confirmation.',route:'attendance',selector:'button[type="submit"], button[name*="save"]'}
    ]},
    copilot:{label:'How to use AI Copilot',icon:'bi-stars',steps:[
      {title:'Open AI Copilot',text:'Open the AI Copilot from the sidebar.',route:'copilot',target:'copilot'},
      {title:'Ask a school question',text:'Ask a clear question about school data or an operational task.',route:'copilot',selector:'textarea, input[type="text"], [contenteditable="true"]'},
      {title:'Send the question',text:'Send your question and wait for the Copilot response.',route:'copilot',selector:'button[type="submit"], button[id*="send"], button[id*="ask"]'},
      {title:'Follow up',text:'Use a follow-up question when you need more detail or clarification.',route:'copilot',selector:null}
    ]}
  };

  function createUI(){
    if(state.ui) return state.ui;
    var back=document.createElement('div'), card=document.createElement('div');
    back.className='eduai-tour-backdrop';
    card.className='eduai-tour-card'; card.setAttribute('role','dialog'); card.setAttribute('aria-modal','true');
    card.innerHTML='<button type="button" class="eduai-tour-close" aria-label="Close guide"><i class="bi bi-x-lg"></i></button>'+
      '<div class="eduai-tour-kicker"><i class="bi bi-compass"></i><span>EduAI Product Guide</span></div>'+
      '<h3 class="eduai-tour-title"></h3><p class="eduai-tour-text"></p><div class="eduai-tour-progress"><span></span></div>'+ 
      '<div class="eduai-tour-actions"><div class="left"><button type="button" class="eduai-tour-skip">Skip</button></div>'+ 
      '<div class="right"><button type="button" class="eduai-tour-prev">Back</button><button type="button" class="eduai-tour-next">Next</button></div></div>';
    document.body.appendChild(back); document.body.appendChild(card); state.ui={back:back,card:card};
    card.querySelector('.eduai-tour-close').addEventListener('click',close); card.querySelector('.eduai-tour-skip').addEventListener('click',close);
    card.querySelector('.eduai-tour-prev').addEventListener('click',function(){go(state.index-1);}); card.querySelector('.eduai-tour-next').addEventListener('click',next);
    back.addEventListener('click',close); return state.ui;
  }

  function clearTarget(){ if(state.target){state.target.classList.remove('eduai-guide-target'); state.target.removeAttribute('data-eduai-guide-active'); state.target=null;} }
  function focusTarget(target){
    clearTarget(); if(!target) return;
    state.target=target; target.classList.add('eduai-guide-target'); target.setAttribute('data-eduai-guide-active','true');
    try{target.scrollIntoView({behavior:'smooth',block:'nearest',inline:'nearest'});}catch(e){target.scrollIntoView();}
  }
  function positionCard(target){
    var card=state.ui.card, margin=16, w=Math.min(390,window.innerWidth-margin*2); card.style.width=w+'px';
    if(!target){card.style.left=Math.max(margin,(window.innerWidth-w)/2)+'px';card.style.top=Math.max(margin,(window.innerHeight-card.offsetHeight)/2)+'px';return;}
    var r=target.getBoundingClientRect(), gap=14, left, top;
    if(r.left+w+gap<=window.innerWidth) left=r.right+gap; else if(r.left-w-gap>=0) left=r.left-w-gap; else left=Math.max(margin,(window.innerWidth-w)/2);
    top=r.top; if(top+card.offsetHeight+margin>window.innerHeight) top=window.innerHeight-card.offsetHeight-margin; if(top<margin) top=margin;
    card.style.left=Math.round(left)+'px'; card.style.top=Math.round(top)+'px';
  }
  function render(){
    var ui=createUI(), step=state.steps[state.index]; if(!step){close();return;}
    var target=targetFor(step); focusTarget(target);
    ui.back.classList.add('show'); ui.card.classList.add('show');
    ui.card.querySelector('.eduai-tour-title').textContent=step.title;
    ui.card.querySelector('.eduai-tour-text').textContent=typeof step.text==='function'?step.text():step.text;
    ui.card.querySelector('.eduai-tour-prev').style.display=state.index>0?'':'none';
    ui.card.querySelector('.eduai-tour-next').textContent=state.index===state.steps.length-1?'Finish':'Next';
    ui.card.querySelector('.eduai-tour-progress span').style.width=(((state.index+1)/state.steps.length)*100)+'%';
    window.requestAnimationFrame(function(){positionCard(target);});
  }
  function start(steps,mode,workflow,index){
    if(!steps||!steps.length)return; createUI(); state.steps=steps;state.mode=mode||'tour';state.workflow=workflow||'';state.index=Math.max(0,Math.min(index||0,steps.length-1));
    document.documentElement.classList.add('eduai-tour-active'); render();
  }
  function close(){
    if(!state.ui)return; clearTarget(); state.index=-1;state.ui.back.classList.remove('show');state.ui.card.classList.remove('show');document.documentElement.classList.remove('eduai-tour-active');
    if(state.mode==='tour'){try{localStorage.setItem(storageKey,'1');}catch(e){}}
  }
  function next(){
    if(state.index<0)return; if(state.index>=state.steps.length-1){close();return;}
    var current=state.steps[state.index], following=state.steps[state.index+1];
    if(state.mode==='workflow'&&following.route&&following.route!==current.route){var destination=route(following.route);if(destination){try{sessionStorage.setItem('eduai_workflow_active',state.workflow);}catch(e){}window.location.href=urlWithState(destination,state.workflow,state.index+1);return;}}
    state.index++;render();
  }
  function go(index){if(index<0)index=0;if(index>=state.steps.length){close();return;}state.index=index;render();}
  function startWorkflow(name){var wf=workflows[name];if(!wf)return;var first=wf.steps[0],destination=route(first.route);if(destination){try{sessionStorage.setItem('eduai_workflow_active',name);}catch(e){}window.location.href=urlWithState(destination,name,0);}else start(wf.steps,'workflow',name,0);}
  function continueWorkflowFromURL(){var p=new URLSearchParams(window.location.search),name=p.get('eduai_workflow');if(!name||!workflows[name])return false;var index=parseInt(p.get('eduai_step')||'0',10);if(isNaN(index))index=0;start(workflows[name].steps,'workflow',name,index);return true;}
  function bind(){
    document.addEventListener('click',function(e){
      var guide=e.target.closest&&e.target.closest('#eduaiGuideBtn,#eduaiFloatingGuideBtn,#startTourBtn');
      if(guide){e.preventDefault();window.eduAIStartProductTour();return;}
      var workflow=e.target.closest&&e.target.closest('[data-eduai-start-workflow],[data-eduai-workflow]');
      if(workflow){e.preventDefault();window.eduAIStartWorkflow(workflow.getAttribute('data-eduai-start-workflow')||workflow.getAttribute('data-eduai-workflow'));}
    });
    if(continueWorkflowFromURL())return;
    var seen=false;try{seen=localStorage.getItem(storageKey)==='1';}catch(e){}
    if(!seen)window.setTimeout(function(){window.eduAIStartProductTour();},900);
  }
  window.eduAIStartProductTour=function(){start(general,'tour','',0);};
  window.eduAIStartTour=window.eduAIStartProductTour; window.eduAIStartWorkflow=startWorkflow; window.eduAIWorkflows=workflows;
  window.eduAIResetProductTour=function(){try{localStorage.removeItem(storageKey);}catch(e){}window.eduAIStartProductTour();};
  window.addEventListener('resize',function(){if(state.index>=0)positionCard(state.target);});
  window.addEventListener('keydown',function(e){if(state.index<0)return;if(e.key==='Escape')close();else if(e.key==='ArrowRight')next();else if(e.key==='ArrowLeft')go(state.index-1);});
  if(document.readyState==='loading')document.addEventListener('DOMContentLoaded',bind,{once:true});else bind();
})(window,document);
