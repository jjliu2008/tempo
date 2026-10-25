import { createBrowserRouter } from "react-router-dom";

import App from "../App";

/**
 * Route table. Keep it thin: each element should be a page component that
 * composes its logic from `src/features/<feature>/`.
 */
export const router = createBrowserRouter([
  {
    path: "/",
    element: <App />,
  },
]);
