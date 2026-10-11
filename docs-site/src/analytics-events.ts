import ExecutionEnvironment from '@docusaurus/ExecutionEnvironment';
import siteConfig from '@generated/docusaurus.config';
import {installEvents} from './analytics/events';

const events = ExecutionEnvironment.canUseDOM
  ? installEvents({window, document, baseUrl: siteConfig.baseUrl})
  : undefined;

// A new route is a new page view: a demo counts again once the visitor navigates.
export function onRouteDidUpdate() {
  events?.newPage();
}
