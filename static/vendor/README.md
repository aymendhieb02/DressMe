# Vendored Avaturn SDK

`avaturn-sdk.js` is the ESM distribution of `@avaturn/sdk` version 1.1.4, copied unchanged from the installed package in the read-only DressMe frontend. The package's npm metadata reports `MIT` licensing (`npm view @avaturn/sdk@1.1.4 license`). It is used only when an approved `AVATURN_URL` is configured and the user explicitly opens the creator. Its provider account, actual deployment origin and export CORS are not verified here.

`model-viewer.min.js` is the standalone ESM distribution of `@google/model-viewer` version 4.3.1, copied unchanged from the same read-only frontend installation. Its Apache-2.0 license text is included as `MODEL_VIEWER_LICENSE.txt`. It loads only for a user's owned saved avatar; its `src` is a local object URL from an authenticated private download.

MIT permission notice: Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated documentation files to deal in the Software without restriction, including use, copy, modification and distribution, subject to including the copyright and permission notice. The Software is provided "AS IS", without warranty of any kind. The package author is Avaturn. Consult the upstream package for the authoritative license text and terms.
