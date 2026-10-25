import { createBrowserRouter } from "react-router-dom";

import App from "../App";
import CalendarPage from "../features/calendars/CalendarPage";
import CalendarLoginPage from "../features/calendars/CalendarLoginPage";

/**
 * Route table. Keep it thin: each element should be a page component that
 * composes its logic from `src/features/<feature>/`.
 */
export const router = createBrowserRouter([
  {
    path: "/",
    element: <CalendarLoginPage />,
  },
  {
    path: "/calendars",
    element: <CalendarPage />,
  },
  {
    path: "/schedule",
    element: <App />,
  },
]);
