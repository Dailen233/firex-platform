import { createApp } from 'vue'
import { createRouter,createWebHashHistory } from 'vue-router'
import App from './App.vue'
import AtlasView from './views/AtlasView.vue'
import './style.css'
const router=createRouter({history:createWebHashHistory(),routes:[
 {path:'/',redirect:'/atlas'},
 {path:'/atlas',component:AtlasView},
 {path:'/scene/:sceneId',component:()=>import('./views/SceneView.vue')},
 {path:'/:pathMatch(.*)*',redirect:'/atlas'},
]})
createApp(App).use(router).mount('#app')
