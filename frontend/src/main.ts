import { createApp } from "vue";
import { VueQueryPlugin, QueryClient } from "@tanstack/vue-query";
import App from "./App.vue";
import router from "./router";
import "./styles/tokens.css";
import "./styles/global.css";

const app = createApp(App);
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      retry: 1,
      refetchOnWindowFocus: false,
    },
  },
});

app.use(router);
app.use(VueQueryPlugin, { queryClient });
app.mount("#app");
