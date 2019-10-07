# Author: Roger Blomgren <roger.blomgren@iki.fi>
import sdl2
import sdl2.ext
from sdl2 import rect, render
from sdl2.ext.compat import isiterable
import sdl2.sdlttf
import math

from common import Ticker, TICK_LENGTH
from debug import debug
from gamedata import *

WHITE = sdl2.ext.Color(255, 255, 255)
RESOURCES = sdl2.ext.Resources(__file__, "resources")

class HWRenderer(sdl2.ext.TextureSpriteRenderSystem):
    def __init__(self, window):
        self.texture_renderer = sdl2.ext.Renderer(window)
        super().__init__(self.texture_renderer)
        self.factory = sdl2.ext.SpriteFactory(sdl2.ext.TEXTURE, renderer=self.texture_renderer)

    def getFactory(self):
        return self.factory

    def clear(self):
        self.texture_renderer.clear()

    def render(self, sprites):
        assert type(sprites) == list

        r = rect.SDL_Rect(0, 0, 0, 0)
        for item in sprites:
            sp = item.sprite
            r.x = sp.x
            r.y = sp.y
            r.w, r.h = sp.size
            debug("Render (%d, %d)" % (sp.x, sp.y))
            render.SDL_RenderCopyEx(self.sdlrenderer,
                                    sp.texture,
                                    None,
                                    r,
                                    item.heading,
                                    None,
                                    render.SDL_FLIP_NONE)
        # Flip buffers
        render.SDL_RenderPresent(self.sdlrenderer)


class Ship:
    def __init__(self, renderer, ss):
        assert isinstance(ss, NodeSimpleStatus)
        self.update(ss)
        self.renderer = renderer
        self.sprite = renderer.getFactory().from_image(RESOURCES.get_path("rocket.png"))
        self.nodeid = ss.nodeid

    def getStatus(self):
        return NodeSimpleStatus(self.nodeid,
                                round(self.x),
                                round(self.y),
                                self.heading,
                                round(self.velocity),
                                self.tick)

    def update(self, ss):
        assert isinstance(ss, NodeSimpleStatus)
        self.x = float(ss.x)
        self.y = float(ss.y)
        self.heading = ss.heading
        self.velocity = float(ss.velocity)
        self.throttle = 0
        self.turning = 0
        self.tick = ss.tick

    def doTick(self, tick):
        # Do the "calculated" movement
        count = Ticker.diff(self.tick, tick)
        if count == 0:
            return
        # Increase velocity by 0.5 / sec
        self.velocity += count * (self.throttle * 0.5 / 1000.0 * TICK_LENGTH)
        if self.velocity < 0:
            self.velocity = 0
        elif self.velocity > 5:
            self.velocity = 5.0
        if self.turning:
            # Turning rate 20*5 deg/s
            self.heading += count * (self.turning*5)
            if self.heading < 0:
                self.heading += 360
            if self.heading >= 360:
                self.heading -= 360
        moved = count * self.velocity
        angle = math.radians(self.heading)
        dx = -moved * math.sin(angle)
        dy = moved * math.cos(angle)
        self.tick = tick
        self.x -= dx
        self.y -= dy
        debug("Position (%d,%d)" % (round(self.x), round(self.y)))

class GameView:
    def __init__(self, renderer, status, maxx, maxy):
        assert isinstance(status, NodeStatus)

        self.renderer = renderer
        self.maxx = maxx # Window X
        self.maxy = maxy # Window y
        self.name = status.name
        ss = status.simplestatus
        self.tick = ss.tick
        self.player = Ship(renderer, ss)
        self.player.sprite.x = round((maxx / 2) - 20)
        self.player.sprite.y = round((maxy / 2) - 20)
        self.opponents = {}

    def statusChange(self, ss):
        assert isinstance(ss, NodeSimpleStatus)
        if not ss.nodeid in self.opponents:
            debug("New opponent %s" % ss)
            ship = Ship(self.renderer, ss)
            self.opponents[ss.nodeid] = ship
        else:
            self.opponents[ss.nodeid].update(ss)

    def render(self, tick):
        if Ticker.diff(self.tick, tick) == 0:
            return
        self.tick = tick
        self.player.doTick(tick)
        # What are the map coordinates for our view?
        mapX = self.player.x - self.maxx / 2.0
        mapY = self.player.y - self.maxy / 2.0
        debug("Map corner (%d, %d)" % (round(mapX), round(mapY)))
        visible = []
        visible.append(self.player)
        for ship in self.opponents.values():
            ship.doTick(tick)
            debug("Opponent (%d,%d)" % (round(ship.x),round(ship.y)))
            if ship.x >= mapX and ship.x <= mapX + self.maxx \
               and ship.y >= mapY and ship.y <= mapY + self.maxy:
                # It's in our view, calculate draw pos
                ship.sprite.x = round(abs(ship.x - mapX) - 20)
                ship.sprite.y = round(abs(ship.y - mapY) - 20)
                visible.append(ship)

        self.renderer.render(visible)

class GameHandler:
    def __init__(self):
        debug("Show window")
        sdl2.ext.init()
        self.window = sdl2.ext.Window("STQ", size=(800, 600))
        self.window.show()
        self.world = sdl2.ext.World()
        self.renderer = HWRenderer(self.window)
        self.world.add_system(self.renderer)

        self.init = False
        self.running = False

    def start(self, status):
        assert isinstance(status, NodeStatus)
        if not self.init:
            self.game = GameView(self.renderer, status, 800, 600)
            self.init = True
            self.running = True

    def statusChange(self, ss):
        assert isinstance(ss, NodeSimpleStatus)
        if self.init:
            self.game.statusChange(ss)

    def getStatus(self):
        return self.game.player.getStatus()

    def handleEvents(self, ticker):
        assert isinstance(ticker, Ticker)

        events = sdl2.ext.get_events()
        for event in events:
            if event.type == sdl2.SDL_QUIT:
                self.running = False
                debug("Quit..")
                break
            if event.type == sdl2.SDL_KEYDOWN:
                if event.key.keysym.sym == sdl2.SDLK_UP:
                    self.game.player.throttle = 1
                elif event.key.keysym.sym == sdl2.SDLK_DOWN:
                    self.game.player.throttle = -1
                elif event.key.keysym.sym == sdl2.SDLK_LEFT:
                    self.game.player.turning = -1
                elif event.key.keysym.sym == sdl2.SDLK_RIGHT:
                    self.game.player.turning = 1

            elif event.type == sdl2.SDL_KEYUP:
                if event.key.keysym.sym in (sdl2.SDLK_UP, sdl2.SDLK_DOWN):
                    self.game.player.throttle = 0
                if event.key.keysym.sym in (sdl2.SDLK_LEFT, sdl2.SDLK_RIGHT):
                    self.game.player.turning = 0

        if self.running:
            self.renderer.clear()
            self.game.render(ticker.getTick())

