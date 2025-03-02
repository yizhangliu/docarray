import copy
import json
import os.path
import tempfile
import threading
import time
import warnings
from collections import Counter
from math import sqrt, ceil, floor
from typing import Optional, Tuple

import numpy as np

from docarray.helper import _get_array_info


class PlotMixin:
    """Helper functions for plotting the arrays."""

    def _ipython_display_(self):
        """Displays the object in IPython as a side effect"""
        self.summary()

    def summary(self):
        """Print the structure and attribute summary of this DocumentArray object.

        .. warning::
            Calling {meth}`.summary` on large DocumentArray can be slow.

        """

        from rich.table import Table
        from rich.console import Console
        from rich.panel import Panel
        import rich.markup

        from rich import box

        tables = []
        console = Console()

        (
            is_homo,
            _nested_in,
            _nested_items,
            attr_counter,
            all_attrs_names,
        ) = _get_array_info(self)

        table = Table(box=box.SIMPLE, highlight=True)
        table.show_header = False
        table.add_row('Type', self.__class__.__name__)
        table.add_row('Length', str(len(self)))
        table.add_row('Homogenous Documents', str(is_homo))

        if _nested_in:
            table.add_row('Has nested Documents in', str(tuple(_nested_in)))

        if is_homo:
            table.add_row('Common Attributes', str(list(attr_counter.items())[0][0]))

        for item in _nested_items:
            table.add_row(item['name'], item['value'])

        is_multimodal = all(d.is_multimodal for d in self)
        table.add_row('Multimodal dataclass', str(is_multimodal))

        if getattr(self, '_subindices', None):
            table.add_row(
                'Subindices', rich.markup.escape(str(tuple(self._subindices.keys())))
            )

        tables.append(Panel(table, title='Documents Summary', expand=False))

        all_attrs_names = tuple(sorted(all_attrs_names))
        if all_attrs_names:

            attr_table = Table(box=box.SIMPLE, highlight=True)
            attr_table.add_column('Attribute')
            attr_table.add_column('Data type')
            attr_table.add_column('#Unique values')
            attr_table.add_column('Has empty value')

            for _a_name in all_attrs_names:

                try:
                    _a = [getattr(d, _a_name) for d in self]
                    _a = set(_a)
                except:
                    pass  # intentional ignore as some fields are not hashable

                _set_type_a = set(type(_aa).__name__ for _aa in _a)
                attr_table.add_row(
                    _a_name,
                    str(tuple(_set_type_a)),
                    str(len(_a)),
                    str(any(_aa is None for _aa in _a)),
                )
            tables.append(Panel(attr_table, title='Attributes Summary', expand=False))

        storage_infos = self._get_storage_infos()
        if storage_infos:
            storage_table = Table(box=box.SIMPLE, highlight=True)
            storage_table.show_header = False
            for k, v in storage_infos.items():
                storage_table.add_row(k, v)

            tables.append(
                Panel(
                    storage_table,
                    title=f'[bold]{self.__class__.__name__}[/bold] Config',
                    expand=False,
                )
            )

        console.print(*tables)

    def plot_embeddings(
        self,
        title: str = 'MyDocumentArray',
        path: Optional[str] = None,
        image_sprites: bool = False,
        min_image_size: int = 16,
        channel_axis: int = -1,
        start_server: bool = True,
        host: str = '127.0.0.1',
        port: Optional[int] = None,
        image_source: str = 'tensor',
    ) -> str:
        """Interactively visualize :attr:`.embeddings` using the Embedding Projector.

        :param title: the title of this visualization. If you want to compare multiple embeddings at the same time,
                make sure to give different names each time and set ``path`` to the same value.
        :param host: if set, bind the embedding-projector frontend to given host. Otherwise `localhost` is used.
        :param port: if set, run the embedding-projector frontend at given port. Otherwise a random port is used.
        :param image_sprites: if set, visualize the dots using :attr:`.uri` and :attr:`.tensor`.
        :param path: if set, then append the visualization to an existing folder, where you can compare multiple
            embeddings at the same time. Make sure to use a different ``title`` each time .
        :param min_image_size: only used when `image_sprites=True`. the minimum size of the image
        :param channel_axis: only used when `image_sprites=True`. the axis id of the color channel, ``-1`` indicates the color channel info at the last axis
        :param start_server: if set, start a HTTP server and open the frontend directly. Otherwise, you need to rely on ``return`` path and serve by yourself.
        :param image_source: specify where the image comes from, can be ``uri`` or ``tensor``. empty tensor will fallback to uri
        :return: the path to the embeddings visualization info.
        """
        from docarray.helper import random_port, __resources_path__

        path = path or tempfile.mkdtemp()
        emb_fn = f'{title}.tsv'
        meta_fn = f'{title}.metas.tsv'
        config_fn = f'config.json'
        sprite_fn = f'{title}.png'

        if image_sprites:
            img_per_row = ceil(sqrt(len(self)))
            canvas_size = min(img_per_row * min_image_size, 8192)
            img_size = max(int(canvas_size / img_per_row), min_image_size)

            max_docs = ceil(canvas_size / img_size) ** 2
            if len(self) > max_docs:
                warnings.warn(
                    f'''
                    {self!r} has more than {max_docs} elements, which is the maximum number of image sprites can support. 
                    The resulting visualization may not be correct. You can do the following:
                    
                    - use fewer images: `da[:10000].plot_embeddings()`
                    - reduce the `min_image_size` to a smaller number, say 8 or 4 (but bear in mind you can hardly recognize anything with a 4x4 image)
                    - turn off `image_sprites` via `da.plot_embeddings(image_sprites=False)`
                    '''
                )

            self.plot_image_sprites(
                os.path.join(path, sprite_fn),
                canvas_size=canvas_size,
                min_size=min_image_size,
                channel_axis=channel_axis,
                image_source=image_source,
            )

        self.save_embeddings_csv(os.path.join(path, emb_fn), delimiter='\t')

        _exclude_fields = ('embedding', 'tensor', 'scores')
        with_header = True
        if len(set(self[0].non_empty_fields).difference(set(_exclude_fields))) <= 1:
            with_header = False

        self.save_csv(
            os.path.join(path, meta_fn),
            exclude_fields=_exclude_fields,
            dialect='excel-tab',
            with_header=with_header,
        )

        _epj_config = {
            'embeddings': [
                {
                    'tensorName': title,
                    'tensorShape': list(self.embeddings.shape),
                    'tensorPath': f'/static/{emb_fn}',
                    'metadataPath': f'/static/{meta_fn}',
                    'sprite': {
                        'imagePath': f'/static/{sprite_fn}',
                        'singleImageDim': (img_size,) * 2,
                    }
                    if image_sprites
                    else {},
                }
            ]
        }

        if os.path.exists(os.path.join(path, config_fn)):
            with open(os.path.join(path, config_fn)) as fp:
                old_config = json.load(fp)
                _epj_config['embeddings'].extend(old_config.get('embeddings', []))

        with open(os.path.join(path, config_fn), 'w') as fp:
            json.dump(_epj_config, fp)

        import gzip

        with gzip.open(
            os.path.join(__resources_path__, 'embedding-projector/index.html.gz'), 'rt'
        ) as fr, open(os.path.join(path, 'index.html'), 'w') as fp:
            fp.write(fr.read())

        if start_server:

            def _get_fastapi_app():
                from fastapi import FastAPI
                from starlette.middleware.cors import CORSMiddleware
                from starlette.staticfiles import StaticFiles

                app = FastAPI()
                app.add_middleware(
                    CORSMiddleware,
                    allow_origins=['*'],
                    allow_credentials=True,
                    allow_methods=['*'],
                    allow_headers=['*'],
                )
                app.mount('/static', StaticFiles(directory=path), name='static')
                return app

            import uvicorn

            app = _get_fastapi_app()
            port = port or random_port()
            t_m = threading.Thread(
                target=uvicorn.run,
                kwargs=dict(app=app, host=host, port=port, log_level='error'),
                daemon=True,
            )
            url_html_path = f'http://{host}:{port}/static/index.html?config={config_fn}'
            t_m.start()
            try:
                _env = str(get_ipython())  # noqa
                if 'ZMQInteractiveShell' in _env:
                    _env = 'jupyter'
                elif 'google.colab' in _env:
                    _env = 'colab'
            except:
                _env = 'local'
            if _env == 'jupyter':
                time.sleep(
                    1
                )  # jitter is required otherwise encouter werid `strict-origin-when-cross-origin` error in browser
                from IPython.display import IFrame, display  # noqa

                display(IFrame(src=url_html_path, width="100%", height=600))
                warnings.warn(
                    f'Showing iframe in cell, you may want to open {url_html_path} in a new tab for better experience. '
                    f'Also, `localhost` may need to be changed to the IP address if your jupyter is running remotely. '
                    f'Click "stop" button in the toolbar to move to the next cell.'
                )
            elif _env == 'colab':
                from google.colab.output import eval_js  # noqa

                colab_url = eval_js(f'google.colab.kernel.proxyPort({port})')
                colab_url += f'/static/index.html?config={config_fn}'
                warnings.warn(
                    f'Showing iframe in cell, you may want to open {colab_url} in a new tab for better experience. '
                    f'Click "stop" button in the toolbar to move to the next cell.'
                )
                time.sleep(
                    1
                )  # jitter is required otherwise encouter werid `strict-origin-when-cross-origin` error in browser
                from IPython.display import IFrame, display

                display(IFrame(src=colab_url, width="100%", height=600))
            elif _env == 'local':
                try:
                    import webbrowser

                    webbrowser.open(url_html_path, new=2)
                except:
                    pass  # intentional pass, browser support isn't cross-platform
                finally:
                    print(
                        f'You should see a webpage opened in your browser, '
                        f'if not, you may open {url_html_path} manually'
                    )
            t_m.join()
        return path

    def save_gif(
        self,
        output: str,
        channel_axis: int = -1,
        duration: int = 200,
        size_ratio: float = 1.0,
        inline_display: bool = False,
        image_source: str = 'tensor',
        skip_empty: bool = False,
        show_index: bool = False,
        show_progress: bool = False,
    ) -> None:
        """
        Save a gif of the DocumentArray. Each frame corresponds to a Document.uri/.tensor in the DocumentArray.

        :param output: the file path to save the gif to.
        :param channel_axis: the color channel axis of the tensor.
        :param duration: the duration of each frame in milliseconds.
        :param size_ratio: the size ratio of each frame.
        :param inline_display: if to show the gif in Jupyter notebook.
        :param image_source: the source of the image in Document atribute.
        :param skip_empty: if to skip empty documents.
        :param show_index: if to show the index of the document in the top-right corner.
        :param show_progress: if to show a progress bar.
        :return:
        """

        from rich.progress import track
        from PIL import Image, ImageDraw

        def img_iterator(channel_axis):
            for _idx, d in enumerate(
                track(self, description='Plotting', disable=not show_progress)
            ):

                if not d.uri and d.tensor is None:
                    if skip_empty:
                        continue
                    else:
                        raise ValueError(
                            f'Document has neither `uri` nor `tensor`, can not be plotted'
                        )

                _d = copy.deepcopy(d)

                if image_source == 'uri' or (
                    image_source == 'tensor' and _d.content_type != 'tensor'
                ):
                    _d.load_uri_to_image_tensor()
                    channel_axis = -1
                elif image_source not in ('uri', 'tensor'):
                    raise ValueError(f'image_source can be only `uri` or `tensor`')

                _d.set_image_tensor_channel_axis(channel_axis, -1)
                if size_ratio < 1:
                    img_size_h, img_size_w, _ = _d.tensor.shape
                    _d.set_image_tensor_shape(
                        shape=(
                            int(size_ratio * img_size_h),
                            int(size_ratio * img_size_w),
                        )
                    )

                if show_index:
                    _img = Image.fromarray(_d.tensor)
                    draw = ImageDraw.Draw(_img)
                    draw.text((0, 0), str(_idx), (255, 255, 255))
                    _d.tensor = np.asarray(_img)

                yield Image.fromarray(_d.tensor).convert('RGB')

        imgs = img_iterator(channel_axis)
        img = next(imgs)  # extract first image from iterator

        with open(output, 'wb') as fp:
            img.save(
                fp=fp,
                format='GIF',
                append_images=imgs,
                save_all=True,
                duration=duration,
                loop=0,
            )

        if inline_display:
            from IPython.display import Image, display

            display(Image(output))

    def plot_image_sprites(
        self,
        output: Optional[str] = None,
        canvas_size: int = 512,
        min_size: int = 16,
        channel_axis: int = -1,
        image_source: str = 'tensor',
        skip_empty: bool = False,
        show_progress: bool = False,
        show_index: bool = False,
        fig_size: Optional[Tuple[int, int]] = (10, 10),
        keep_aspect_ratio: bool = False,
    ) -> None:
        """Generate a sprite image for all image tensors in this DocumentArray-like object.

        An image sprite is a collection of images put into a single image. It is always square-sized.
        Each sub-image is also square-sized and equally-sized.

        :param output: Optional path to store the visualization. If not given, show in UI
        :param canvas_size: the size of the canvas
        :param min_size: the minimum size of the image
        :param channel_axis: the axis id of the color channel, ``-1`` indicates the color channel info at the last axis
        :param image_source: specify where the image comes from, can be ``uri`` or ``tensor``. empty tensor will fallback to uri
        :param skip_empty: skip Document who has no .uri or .tensor.
        :param show_index: show the index on the top-right corner of every image
        :param fig_size: the size of the figure
        :param show_progress: show a progressbar while plotting.
        :param keep_aspect_ratio: preserve the aspect ratio of the image by using the aspect ratio of the first image in self.
        """
        if not self:
            raise ValueError(f'{self!r} is empty')

        import matplotlib.pyplot as plt

        img_per_row = ceil(sqrt(len(self)))
        img_size = int(canvas_size / img_per_row)

        if img_size < min_size:
            # image is too small, recompute the size
            img_size = min_size
            img_per_row = int(canvas_size / img_size)
        
        img_per_col = ceil(len(self) / img_per_row)

        if img_per_row == 0:
            img_per_row = 1

        img_per_col = ceil(len(self) / img_per_row)
        max_num_img = img_per_row * img_per_col
        sprite_img = np.zeros(
            [img_size * img_per_col, img_size * img_per_row, 3], dtype='uint8'
        )
        img_size_w, img_size_h = img_size, img_size
        set_aspect_ratio = False

        from rich.progress import track
        from PIL import Image, ImageDraw

        try:
            for _idx, d in enumerate(
                track(self, description='Plotting', disable=not show_progress)
            ):

                if not d.uri and d.tensor is None:
                    if skip_empty:
                        continue
                    else:
                        raise ValueError(
                            f'Document has neither `uri` nor `tensor`, can not be plotted'
                        )

                _d = copy.deepcopy(d)

                if image_source == 'uri' or (
                    image_source == 'tensor' and _d.content_type != 'tensor'
                ):
                    _d.load_uri_to_image_tensor()
                    channel_axis = -1
                elif image_source not in ('uri', 'tensor'):
                    raise ValueError(f'image_source can be only `uri` or `tensor`')

                _d.set_image_tensor_channel_axis(channel_axis, -1)

                if keep_aspect_ratio and not set_aspect_ratio:
                    h, w, _ = _d.tensor.shape
                    img_size_h = int(h * img_size / w)
                    sprite_img = np.zeros(
                        [img_size_h * img_per_col, img_size_w * img_per_row, 3],
                        dtype='uint8',
                    )
                    set_aspect_ratio = True

                _d.set_image_tensor_shape(shape=(img_size_h, img_size_w))

                row_id = floor(_idx / img_per_row)
                col_id = _idx % img_per_row

                if show_index:
                    _img = Image.fromarray(np.asarray(_d.tensor, dtype='uint8'))
                    draw = ImageDraw.Draw(_img)
                    draw.text((0, 0), str(_idx), (255, 255, 255))
                    _d.tensor = np.asarray(_img)

                sprite_img[
                    (row_id * img_size_h) : ((row_id + 1) * img_size_h),
                    (col_id * img_size_w) : ((col_id + 1) * img_size_w),
                ] = _d.tensor

        except Exception as ex:
            raise ValueError(
                'Bad image tensor. Try different `image_source` or `channel_axis`'
            ) from ex

        im = Image.fromarray(sprite_img)

        if output:
            with open(output, 'wb') as fp:
                im.save(fp)
        else:
            plt.figure(figsize=fig_size, frameon=False)
            plt.gca().set_axis_off()
            plt.subplots_adjust(top=1, bottom=0, right=1, left=0, hspace=0, wspace=0)
            plt.margins(0, 0)
            plt.gca().xaxis.set_major_locator(plt.NullLocator())
            plt.gca().yaxis.set_major_locator(plt.NullLocator())
            plt.imshow(im)
            plt.show()
