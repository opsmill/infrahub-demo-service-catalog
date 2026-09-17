import { createApp } from '@backstage/frontend-defaults';
import catalogPlugin from '@backstage/plugin-catalog/alpha';
import { navModule } from './modules/nav';
import { homeModule } from './modules/home';
import {
  infrahubModule,
  infrahubPlugin,
} from '@opsmill/backstage-plugin-infrahub';
import { themeModule } from './modules/theme';

export default createApp({
  features: [
    catalogPlugin,
    navModule,
    themeModule,
    homeModule,
    infrahubModule,
    infrahubPlugin,
  ],
});
