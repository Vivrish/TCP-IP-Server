import socket
import re
import threading
import time
from enum import Enum

PORT = 7777

keys = {
    23019: 32037,
    32037: 29295,
    18789: 13603,
    16443: 29533,
    18189: 21952
}


# Server id : client id

class State(Enum):
    CLIENT_USERNAME = 1
    CLIENT_KEY_ID = 2
    CLIENT_CONFIRMATION = 3
    INITIAL_MOVE = 4
    DEFINE_LOCATION = 5
    DEFINE_DIRECTION = 6
    CLIENT_OK = 7
    ROTATION = 8
    CLIENT_MESSAGE = 9
    LOGOUT = 10
    TERMINATE_CONNECTION = 11
    EVADE = 12
    CLIENT_RECHARGING = 13
    CLIENT_FULL_POWER = 14
    UNKNOWN = 15


class ResponseType(Enum):
    RESPONSE_REQUIRED = 1
    NO_RESPONSE_NEEDED = 2
    DOUBLE_RESPONSE_REQUIRED = 3


class Direction(Enum):
    NORTH = 1
    EAST = 2
    SOUTH = 3
    WEST = 4
    UNKNOWN = 5


class Axis(Enum):
    X = 1
    Y = 2


class Robot:
    def __init__(self):
        self.x = 1000
        self.y = 1000
        self.lastX = -1000
        self.lastY = -1000
        self.hash = ""
        self.name = ""
        self.clientKey = -1
        self.direction = Direction.UNKNOWN
        self.directionIsRight = False
        self.neededDirection = Direction.UNKNOWN
        self.inverseNavigation = False

    def calculateHash(self) -> str:
        if self.clientKey == -1:
            raise RuntimeError("Attempt to calculate hash before key assignment")
        asciiSum = 0
        for i in self.name:
            asciiSum += ord(i)
        self.hash = str((((asciiSum * 1000) % 65536) + self.clientKey) % 65536)
        return self.hash

    def setLocation(self, message: str):
        self.lastX = self.x
        self.lastY = self.y
        coords = [int(d) for d in re.findall(r'-?\d+', message)]
        print(f"Location for robot set: {self.x} {self.y} facing {self.direction}")
        self.x = int(coords[0])
        self.y = int(coords[1])

    def isOnLocation(self, x: int, y: int):
        return self.x == x and self.y == y

    def positionChanged(self):
        return not (self.x == self.lastX and self.y == self.lastY)

    def defineDirection(self):
        if self.x > self.lastX:
            self.direction = Direction.EAST
        elif self.x < self.lastX:
            self.direction = Direction.WEST
        elif self.y > self.lastY:
            self.direction = Direction.NORTH
        elif self.y < self.lastY:
            self.direction = Direction.SOUTH

    def facingRightDirection(self):
        return self.direction == self.neededDirection

    def calculateDirection(self):
        if self.inverseNavigation:
            self.inverseCalculateDirection()
            return
        if self.y < 0:
            self.neededDirection = Direction.NORTH
        elif self.y > 0:
            self.neededDirection = Direction.SOUTH
        elif self.x < 0:
            self.neededDirection = Direction.EAST
        elif self.x > 0:
            self.neededDirection = Direction.WEST

    def inverseCalculateDirection(self):
        if self.x < 0:
            self.neededDirection = Direction.EAST
        elif self.x > 0:
            self.neededDirection = Direction.WEST
        elif self.y < 0:
            self.neededDirection = Direction.NORTH
        elif self.y > 0:
            self.neededDirection = Direction.SOUTH

    def changeDirection(self):
        # Only considering turning right
        if self.direction.value == len(Direction) - 1:
            self.direction = Direction(1)
            return
        self.direction = Direction(self.direction.value + 1)
        print(f"{self.direction})")


class Server:
    def __init__(self, clientSocket: socket.socket, robot: Robot):
        self.state = State.CLIENT_USERNAME
        self.responseType = ResponseType.RESPONSE_REQUIRED
        self.clientSocket = clientSocket
        self.message = "To be received"
        self.previousResponse = "To be generated"
        self.response = "To be generated"
        self.robot = robot
        self.hash = ""
        self.serverKey = -1
        self.terminateConnection = False
        self.previousState = State.UNKNOWN

        self.responses = {
            State.CLIENT_USERNAME: self.processUsername,
            State.CLIENT_KEY_ID: self.processKeyId,
            State.CLIENT_CONFIRMATION: self.processConfirmation,
            State.INITIAL_MOVE: self.initialMove,
            State.DEFINE_LOCATION: self.defineLocation,
            State.DEFINE_DIRECTION: self.defineDirection,
            State.CLIENT_OK: self.processOk,
            State.EVADE: self.evade,
            State.CLIENT_MESSAGE: self.processMessage,
            State.LOGOUT: self.logOut,
            State.CLIENT_RECHARGING: self.recharge

        }

        self.commands = {
            "SERVER_CONFIRMATION": "Nothing yet",
            "SERVER_MOVE": "102 MOVE\a\b",
            "SERVER_TURN_LEFT": "103 TURN LEFT\a\b",
            "SERVER_TURN_RIGHT": "104 TURN RIGHT\a\b",
            "SERVER_PICK_UP": "105 GET MESSAGE\a\b",
            "SERVER_LOGOUT": "106 LOGOUT\a\b",
            "SERVER_KEY_REQUEST": "107 KEY REQUEST\a\b",
            "SERVER_OK": "200 OK\a\b",
            "SERVER_LOGIN_FAILED": "300 LOGIN FAILED\a\b",
            "SERVER_SYNTAX_ERROR": "301 SYNTAX ERROR\a\b",
            "SERVER_LOGIC_ERROR": "302 LOGIC ERROR\a\b",
            "SERVER_KEY_OUT_OF_RANGE_ERROR": "303 KEY OUT OF RANGE\a\b"
        }

        self.maxLength = {
            State.CLIENT_USERNAME: 20,
            State.CLIENT_KEY_ID: 5,
            State.CLIENT_CONFIRMATION: 7,
            State.INITIAL_MOVE: 12,
            State.DEFINE_LOCATION: 12,
            State.DEFINE_DIRECTION: 12,
            State.CLIENT_OK: 12,
            State.ROTATION: 12,
            State.CLIENT_MESSAGE: 100,
            State.LOGOUT: 100,
            State.TERMINATE_CONNECTION: 0,
            State.EVADE: 12,
            State.CLIENT_RECHARGING: 12,
            State.CLIENT_FULL_POWER: 12
        }

    def calculateHash(self) -> None:
        if self.serverKey == -1:
            raise RuntimeError("Attempt to calculate hash before key assignment")
        asciiSum = 0
        for i in self.robot.name:
            asciiSum += ord(i)
        self.hash = str((((asciiSum * 1000) % 65536) + self.serverKey) % 65536)

    def getMessage(self):
        msg = ""
        prev = ""
        current = ""
        rechargeFlag = False

        while True:
            prev = current
            current = self.clientSocket.recv(1).decode()
            msg += current
            if prev == '\a' and current == '\b':
                break

            if len(msg) >= self.maxLength[self.state]:
                if msg[:5] == "RECHA" or msg[:5] == "FULL ":
                    self.previousState = self.state
                    self.state = State.CLIENT_RECHARGING
                    rechargeFlag = True
                    continue
                self.response = self.handleError(SyntaxError)
                raise SyntaxError

        print(f"Got message: {repr(msg)} {self.state}")
        self.message = msg
        if ("RECHARGING" in self.message or "FULL POWER" in self.message) and not rechargeFlag:
            if "FULL POWER" in self.message and self.state == State.CLIENT_RECHARGING:
                return
            self.previousState = self.state
            self.state = State.CLIENT_RECHARGING

    def formatMessage(self):
        self.message = self.message[:-2]

    def generateResponse(self):
        # Method call
        try:
            rawCommand = self.responses[self.state]()
        except IndexError as error:
            self.response = self.handleError(IndexError)
        else:
            self.response = self.commands[rawCommand]

    def handleError(self, error) -> str:
        print(f"Error detected: {error}")
        self.state = State.TERMINATE_CONNECTION
        response = "Nothing yet"
        if error == SyntaxError:
            response = "SERVER_SYNTAX_ERROR"
        elif error == IndexError:
            response = "SERVER_KEY_OUT_OF_RANGE_ERROR"
        elif error == RuntimeError:
            response = "SERVER_LOGIC_ERROR"
        return self.commands[response]

    def sendMessage(self) -> None:
        self.clientSocket.send(self.response.encode())
        self.previousResponse = self.response
        print(f"Sent message: {repr(self.response)} State: {self.state}")

    def processUsername(self) -> str:
        self.robot.name = self.message
        self.state = State.CLIENT_KEY_ID
        return "SERVER_KEY_REQUEST"

    def processKeyId(self) -> str:
        try:
            self.serverKey = list(keys.keys())[int(self.message)]
        except ValueError as e:
            self.response = self.handleError(SyntaxError)
            raise ValueError
        self.robot.clientKey = keys[self.serverKey]
        self.calculateHash()
        self.robot.calculateHash()
        self.state = State.CLIENT_CONFIRMATION
        self.commands["SERVER_CONFIRMATION"] = self.hash + "\a\b"
        return "SERVER_CONFIRMATION"

    def processConfirmation(self) -> str:
        self.checkConfirmation()
        if self.message == self.robot.hash:
            self.state = State.INITIAL_MOVE
            self.responseType = ResponseType.DOUBLE_RESPONSE_REQUIRED
            return "SERVER_OK"
        else:
            self.state = State.TERMINATE_CONNECTION
            return "SERVER_LOGIN_FAILED"

    def checkConfirmation(self):
        for symbol in self.message:
            if not (symbol.isdigit() or symbol == '-'):
                self.response = self.handleError(SyntaxError)
                raise SyntaxError

    def checkForFloats(self):
        pattern = r"[0-9]\.[0-9]"
        if len(re.findall(pattern, self.message)) > 0 and self.previousResponse in [self.commands["SERVER_MOVE"],
                                                                                    self.commands["SERVER_TURN_RIGHT"]]:
            self.response = self.handleError(SyntaxError)
            raise SyntaxError

    def checkForTooManySpaces(self):
        pattern = ' '
        if len(re.findall(pattern, self.message)) > 2 and self.previousResponse in [self.commands["SERVER_MOVE"],
                                                                                    self.commands["SERVER_TURN_RIGHT"]]:
            self.response = self.handleError(SyntaxError)
            raise SyntaxError

    def initialMove(self):
        self.state = State.DEFINE_LOCATION
        return "SERVER_MOVE"

    def defineLocation(self) -> str:
        self.checkForFloats()
        self.checkForTooManySpaces()
        self.robot.setLocation(self.message)
        if self.robot.isOnLocation(0, 0):
            self.state = State.CLIENT_MESSAGE
            return self.processMessage()
        self.state = State.DEFINE_DIRECTION
        return "SERVER_MOVE"

    def defineDirection(self) -> str:
        self.checkForFloats()
        self.checkForTooManySpaces()
        self.robot.setLocation(self.message)
        if not self.robot.positionChanged():
            self.state = State.EVADE
            return "SERVER_TURN_RIGHT"
        self.robot.defineDirection()
        if self.robot.isOnLocation(0, 0):
            self.state = State.CLIENT_MESSAGE
            return self.processMessage()

        self.state = State.CLIENT_OK
        self.robot.calculateDirection()
        if self.robot.facingRightDirection():
            return "SERVER_MOVE"
        else:
            self.robot.changeDirection()
            return "SERVER_TURN_RIGHT"

    def processOk(self) -> str:
        self.checkForFloats()
        self.checkForTooManySpaces()
        self.robot.setLocation(self.message)
        if self.robot.isOnLocation(0, 0):
            self.state = State.CLIENT_MESSAGE
            return self.processMessage()
        if not self.robot.positionChanged() and self.previousResponse == self.commands["SERVER_MOVE"]:
            print("Obstacle encountered")
            self.robot.inverseNavigation = not self.robot.inverseNavigation
            self.state = State.EVADE
            self.robot.changeDirection()
            return "SERVER_TURN_RIGHT"
        self.robot.calculateDirection()
        if self.robot.facingRightDirection():
            return "SERVER_MOVE"
        else:
            self.robot.changeDirection()
            return "SERVER_TURN_RIGHT"

    def evade(self) -> str:
        self.checkForFloats()
        self.checkForTooManySpaces()
        self.robot.setLocation(self.message)
        self.state = State.DEFINE_DIRECTION
        return "SERVER_MOVE"

    def processMessage(self) -> str:
        self.state = State.LOGOUT
        return "SERVER_PICK_UP"

    def logOut(self) -> str:
        self.state = State.TERMINATE_CONNECTION
        return "SERVER_LOGOUT"

    def recharge(self):
        if self.message == "FULL POWER":
            self.response = self.handleError(RuntimeError)
            raise RuntimeError
        self.clientSocket.settimeout(5)
        self.getMessage()
        self.formatMessage()
        if self.message != "FULL POWER":
            self.response = self.handleError(RuntimeError)
            raise RuntimeError
        self.state = self.previousState
        self.clientSocket.settimeout(1)
        self.getMessage()
        self.formatMessage()
        self.generateResponse()
        self.sendMessage()
        return self.response + "\a\b"


def handleClient(clientSocket: socket.socket, address: str) -> None:
    robot = Robot()
    server = Server(clientSocket, robot)
    clientSocket.settimeout(1)

    while True:
        print()
        try:
            server.getMessage()
        except TimeoutError:
            clientSocket.close()
            return
        except SyntaxError:
            server.sendMessage()
            clientSocket.close()
            return
        server.formatMessage()
        try:
            server.generateResponse()
        except (ValueError, SyntaxError, RuntimeError):
            server.sendMessage()
            clientSocket.close()
            return
        except TimeoutError:
            clientSocket.close()
            return
        except KeyError:
            continue
        if server.terminateConnection:
            clientSocket.close()
            return
        server.sendMessage()
        if server.responseType == ResponseType.DOUBLE_RESPONSE_REQUIRED:
            server.responseType = ResponseType.RESPONSE_REQUIRED
            server.generateResponse()
            server.sendMessage()
        if server.state == State.TERMINATE_CONNECTION:
            clientSocket.close()
            return


def main():
    soc = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    soc.bind(("", PORT))
    soc.listen(10)

    while True:
        clientSocket, address = soc.accept()

        thread = threading.Thread(target=handleClient, args=(clientSocket, address))

        thread.start()


if __name__ == "__main__":
    main()
