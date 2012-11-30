# -*- coding: utf-8 -*-

import logging
from os.path import dirname, basename, join

from django import template
from django.db import models
from django.core.cache import cache
from django.core.files.base import File
from django.template import Context
from django.template.loader import get_template
from django.utils.translation import get_language

CACHE_PREFIX = 'chunks_'

Chunk = models.get_model('chunks', 'chunk')
Image = models.get_model('chunks', 'image')
Media = models.get_model('chunks', 'media')

register = template.Library()
logger = logging.getLogger(__name__)


class ChunkNode(template.Node):

    def __init__(self, key, is_variable, cache_time=0, with_template=True,
                template_name=None, tpl_is_variable=False,
                content_type='text'):

        default_templates = dict(
            text='chunks/plain.html',
            image='chunks/image.html',
            media='chunks/media.html'
        )
        if template_name is None:
            self.template_name = default_templates[content_type]
        else:
            if tpl_is_variable:
                self.template_name = template.Variable(template_name)
            else:
                self.template_name = template_name

        self.key = key
        self.is_variable = is_variable
        self.cache_time = cache_time
        self.with_template = with_template
        self.content_type = content_type

    def render(self, context):
        if self.is_variable:
            real_key = template.Variable(self.key).resolve(context)
        else:
            real_key = self.key

        if isinstance(self.template_name, template.Variable):
            real_tpl = self.template_name.resolve(context)
        else:
            real_tpl = self.template_name

        # Eventually we want to pass the whole context to the template so that
        # users have the maximum of flexibility of what to do in there.
        if self.with_template:
            new_ctx = template.Context({})
            new_ctx.update(context)

        sources = dict(text=Chunk, image=Image, media=Media)
        model = sources[self.content_type]

        try:
            obj = None
            if self.cache_time > 0:
                cache_key = CACHE_PREFIX + self.content_type + get_language() + real_key
                obj = cache.get(cache_key)
            if obj is None:
                try:
                    obj = model.objects.get(key=real_key)
                except model.DoesNotExist:
                    obj = model(key=real_key)
                    if self.content_type == 'image':
                        filename = dirname(__file__) + '/' + join('..', 'static', 'chunks', 'stub.png')
                        with open(filename, 'r') as file:
                            obj.image.save(basename(filename), File(file), save=True)
                    else:
                        obj.content = real_key
                        obj.save()

                if self.cache_time != 0:
                    if self.cache_time is None or self.cache_time == 'None':
                        logger.debug("Caching %s for the cache's default timeout"
                                % (real_key,))
                        cache.set(cache_key, obj)
                    else:
                        logger.debug("Caching %s for %s seconds" % (real_key,
                            str(self.cache_time)))
                        cache.set(cache_key, obj, int(self.cache_time))
                else:
                    logger.debug("Don't cache %s" % (real_key,))

            if self.with_template:
                tpl = template.loader.get_template(real_tpl)
                new_ctx.update({'obj': obj})
                return tpl.render(new_ctx)
            elif hasattr(obj, 'image'):
                return obj.image.url
            else:
                return obj.content
        except model.DoesNotExist:
            return u''


class BasicChunkWrapper(object):

    def prepare(self, parser, token):
        u"""
        The parser checks for following tag-configurations::

            {% chunk {key} %}
            {% chunk {key} {timeout} %}
            {% chunk {key} {timeout} {content_type} %}
            {% chunk {key} {timeout} {content_type} {tpl_name} %}
        """
        tokens = token.split_contents()
        self.is_variable = False
        self.tpl_is_variable = False
        self.key = None
        self.cache_time = 0
        self.tpl_name = None
        self.content_type = 'text'

        tag_name, self.key, args = tokens[0], tokens[1], tokens[2:]
        num_args = len(args)

        if num_args not in xrange(4):
            raise template.TemplateSyntaxError, "%r tag should have up to three arguments" % (tokens[0],)

        if num_args >= 1:
            self.cache_time = args[0]
        if num_args >= 2:
            self.content_type = args[1]
        if num_args == 3:
            self.tpl_name = args[2]

        # Check to see if the slug is properly double/single quoted
        if not (self.key[0] == self.key[-1] and self.key[0] in ('"', "'")):
            self.is_variable = True
        else:
            self.key = self.key[1:-1]

        # Clean up the template name
        if self.tpl_name:
            if not(self.tpl_name[0] == self.tpl_name[-1] and self.tpl_name[0] in ('"', "'")):
                self.tpl_is_variable = True
            else:
                self.tpl_name = self.tpl_name[1:-1]

        if self.cache_time is not None and self.cache_time != 'None':
            self.cache_time = int(self.cache_time)

    def __call__(self, parser, token):
        self.prepare(parser, token)
        return ChunkNode(self.key, self.is_variable, self.cache_time,
            template_name=self.tpl_name,
            tpl_is_variable=self.tpl_is_variable,
            content_type=self.content_type)


class PlainChunkWrapper(BasicChunkWrapper):

    def __call__(self, parser, token):
        self.prepare(parser, token)
        return ChunkNode(self.key, self.is_variable, self.cache_time,
            False, content_type=self.content_type)


do_get_chunk = BasicChunkWrapper()
do_plain_chunk = PlainChunkWrapper()

register.tag('chunk', do_get_chunk)
register.tag('chunk_plain', do_plain_chunk)


@register.simple_tag
def chunk_media(key):
    obj = Media.get(key)
    tpl = get_template('chunks/media.html')
    return tpl.render(Context(dict(obj=obj)))


@register.inclusion_tag('chunks/media_list.html')
def chunk_media_list():
    return dict(media=Media.objects.all())
