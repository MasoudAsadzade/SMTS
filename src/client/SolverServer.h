//
// Created by Matteo on 22/07/16.
//

#ifndef CLAUSE_SHARING_SOLVERSERVER_H
#define CLAUSE_SHARING_SOLVERSERVER_H

//#include <ctime>
#include "lib/net.h"
#include "SolverProcess.h"


class SolverServer : public Server {
private:
    void stop_solver();

    void log(uint8_t, std::string, std::map<std::string, std::string> *_ = nullptr);

    bool check_header(std::map<std::string, std::string> &);

    Socket server;
    Socket *lemmas;
    SolverProcess *solver;
protected:
    void handle_close(Socket &);

    void handle_exception(Socket &, SocketException &);

    void handle_message(Socket &, std::map<std::string, std::string> &, std::string &);

public:
    SolverServer(Address &);
};


#endif //CLAUSE_SHARING_SOLVERSERVER_H
