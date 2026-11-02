# Licenses

## KernelGrove

Copyright © 2026 Sergio Fernandez and the KernelGrove contributors.

KernelGrove is free and open source software, licensed under the
**Apache License, Version 2.0**. You may use, modify and redistribute it —
commercially or not — provided you keep the copyright and license notices
and the attribution in the `NOTICE` file, which credits the original project:
<https://github.com/serg4life/kernelgrove>

License: <https://www.apache.org/licenses/LICENSE-2.0>

Unless required by applicable law or agreed to in writing, the software is
distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY
KIND, either express or implied.

## Third-party components

KernelGrove includes the components below, each under its own license.

**Qt, through PySide6 — GNU Lesser General Public License, version 3**
Copyright © The Qt Company Ltd. and contributors.
Qt is dynamically linked, and its libraries are supplied as separate files
that you may replace with your own build of the same version.
License: <https://www.gnu.org/licenses/lgpl-3.0.html>
Project and sources: <https://www.qt.io/> · <https://download.qt.io/> ·
<https://pypi.org/project/PySide6/>

**Inter — SIL Open Font License 1.1**
Copyright © The Inter Project Authors.
License: <https://openfontlicense.org/>
Project: <https://rsms.me/inter/>

**jsonschema, and with it referencing, jsonschema-specifications, rpds-py
and attrs — MIT**
Copyright © 2013 Julian Berman (jsonschema); © 2022 Julian Berman
(referencing, jsonschema-specifications); © 2023 Julian Berman (rpds-py);
© 2015 Hynek Schlawack and the attrs contributors.
Projects: <https://pypi.org/project/jsonschema/> and the links there.

> Permission is hereby granted, free of charge, to any person obtaining a
> copy of this software and associated documentation files (the "Software"),
> to deal in the Software without restriction, including without limitation
> the rights to use, copy, modify, merge, publish, distribute, sublicense,
> and/or sell copies of the Software, and to permit persons to whom the
> Software is furnished to do so, subject to the following conditions:
>
> The above copyright notice and this permission notice shall be included in
> all copies or substantial portions of the Software.
>
> THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
> IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
> FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL
> THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
> LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
> FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
> DEALINGS IN THE SOFTWARE.

**Python, and typing-extensions — Python Software Foundation License 2.0**
Copyright © 2001 Python Software Foundation. The interpreter is embedded in
the packaged builds.
License: <https://docs.python.org/3/license.html>

### Optional compilation tools

The device tree compiler **dtc** and a C preprocessor are **not part of
KernelGrove** and are never needed to run it. They are separate programs,
published by third parties under their own licenses, which KernelGrove runs
as separate processes only when you ask it to compile something. The Windows
installer may offer them as an optional download; they are installed
*alongside* KernelGrove, never inside it, and each keeps its own license.

**dtc, the Device Tree Compiler — GNU General Public License, version 2 or
later**
Copyright © the dtc contributors.
Where a build of dtc is supplied, the complete corresponding source of that
exact build is published beside it, and the license text travels with the
program.
License: <https://www.gnu.org/licenses/old-licenses/gpl-2.0.html>
Project and sources: <https://github.com/dgibson/dtc>

**Clang, from LLVM — Apache License 2.0 with the LLVM exception**
Copyright © the LLVM contributors.
Used unmodified, as the C preprocessor.
License: <https://llvm.org/LICENSE.txt>
Project and sources: <https://llvm.org/> ·
<https://github.com/llvm/llvm-project>

### The bindings database

The database KernelGrove downloads is built from the Linux kernel's device
tree binding schemas and sources, and keeps the licenses those files carry
(mostly `GPL-2.0-only OR BSD-2-Clause`). See
<https://www.kernel.org/doc/html/latest/process/license-rules.html>.
